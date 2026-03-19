import os
import io
import json
import torch
import torch.nn as nn
import torchvision.models as models
import torchvision.transforms as transforms
from PIL import Image
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.staticfiles import StaticFiles

# 資安防線 - 速率限制匯入 SlowAPI 套件
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel
from typing import Optional, List
from fastapi import Query

load_dotenv()
DB_HOST = "db"
DB_NAME = "manhwa"
DB_USER = "postgres"
DB_PASS = os.environ.get("POSTGRES_ROOT_PASSWORD")
DB_PORT = 5432
import google.generativeai as genai
GEMINI_API_KEY=os.environ.get("APIKEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-2.5-flash')
else:
    print("警告: 未設定 GEMINI_API_KEY")


limiter= Limiter(key_func=get_remote_address) #實體化limiter,抓ip用的
app = FastAPI(title="MangaVault AI Engine")
app.state.limiter = limiter
app.mount("/images", StaticFiles(directory="images"), name="images")
app.add_exception_handler(RateLimitExceeded,_rate_limit_exceeded_handler)

origns=[ #新增允許連進來的網頁
    "http://localhost:3000",
    "http://172.20.176.1:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origns,
    allow_credentials=True,
    allow_methods=["POST"],
    allow_headers=["*"],
)
 #使用的model
def calc_gram_matrix(feature_map): #Gram Matrix 將這些特徵圖展平，然後讓它們自己跟自己做內積
    b, c, h, w = feature_map.size()
    features = feature_map.view(b, c, h * w) 
    G = torch.bmm(features, features.transpose(1, 2)) 
    return G.div(h * w)

class DualOutputEncoder(nn.Module):
    def __init__(self, fine_tuned_resnet):
        super(DualOutputEncoder, self).__init__()
        self.base_model = fine_tuned_resnet
        self.base_model.fc = nn.Identity() 
        self.layer1 = nn.Sequential(self.base_model.conv1, self.base_model.bn1, self.base_model.relu, self.base_model.maxpool, self.base_model.layer1)
        self.layer2 = self.base_model.layer2
        self.layer3 = self.base_model.layer3
        self.layer4 = self.base_model.layer4
        self.avgpool = self.base_model.avgpool #拿來最後壓縮用的

    def forward(self, x):
        f1 = self.layer1(x) #淺層特徵, 跟空間有關
        g1 = calc_gram_matrix(f1)  #這邊是代表風格
        f2 = self.layer2(f1) #中層特徵
        g2 = calc_gram_matrix(f2) 
        f3 = self.layer3(f2)#深層特徵
        g3 = calc_gram_matrix(f3) 
        g1_pooled = torch.max(g1, dim=2)[0]
        g2_pooled = torch.max(g2, dim=2)[0]
        g3_pooled = torch.max(g3, dim=2)[0]
        e_sty = torch.cat((g1_pooled, g2_pooled, g3_pooled), dim=1)
        f4 = self.layer4(f3)
        e_sem = self.avgpool(f4)
        e_sem = torch.flatten(e_sem, 1) 
        return e_sem, e_sty
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
base_model= models.resnet18(weights=None)
base_model.fc= nn.Linear(base_model.fc.in_features, 10)
base_model.load_state_dict(torch.load("multi_label_model_epoch_4.pth", map_location=device))
encoder = DualOutputEncoder(base_model).to(device)
encoder.eval()
transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.6272, 0.5589, 0.5401], std=[0.3236, 0.3215, 0.3189])
])
#api節點

@app.post("/api/search_image")
@limiter.limit("5/day")
async def search_similar_manga(
    request: Request, 
    file: UploadFile=File(...),
    focusContent: str = Form("false"),
    focusStyle: str = Form("false")
    ):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid file type. Only images are allowed.")
    is_content = focusContent.lower()== "true"
    is_style = focusStyle.lower()== "true"
    if is_content and not is_style:
        w_sem, w_sty=1.0, 0.0
    elif is_style and not is_content:
        w_sem, w_sty=0.0, 1.0
    else:
        w_sem, w_sty=0.5, 0.5
        
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        
        input_tensor = transform(image).unsqueeze(0).to(device)
        with torch.no_grad():
            e_sem, e_sty= encoder(input_tensor)
        sem_vector =e_sem[0].cpu().numpy().tolist() #轉成python列表
        sty_vector =e_sty[0].cpu().numpy().tolist()
        
        #資料庫
        conn=psycopg2.connect(host=DB_HOST,database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT)
        register_vector(conn)
        cursor=conn.cursor() #生成物件去控制database
        
        search_query = '''
            SELECT manga_name, image_path, labels, (%s * (semantic_feature <=> %s) + %s * (style_feature <=> %s)) AS distance
            FROM anime_images
            WHERE (semantic_feature <=> %s) > 0.01
            ORDER BY distance ASC
            LIMIT 4;
        '''
        # cursor.execute(search_query,(str(sem_vector),))
        cursor.execute(search_query, (
            w_sem, str(sem_vector), 
            w_sty, str(sty_vector),
            str(sem_vector)
        ))
        results=cursor.fetchall()
        formatted_results =[] #裝回傳資料用的
        for row in results :
            formatted_results.append({
                "manga_name": row[0],
                "image_path": row[1],
                # "similarity_score": round(1-float(row[3]), 4),
                "labels":row[2]
            })
        cursor.close()
        conn.close()
        return {"status": "success", "data": formatted_results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
class MangaTitlesRequest(BaseModel):
    titles: List[str]
@app.post("/api/recommend_text")
@limiter.limit("3/day")
async def generate_ai_description(request: Request, data: MangaTitlesRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="未配置 API Key")
    
    titles_str = "、".join(data.titles)
    # prompt = f"You are an experienced manga expert. Based on the following four manga titles: 【{titles_str}】, please provide a fluent English recommendation of about 100 words for each. Focus on briefly introducing the storyline, as well as the artist’s distinctive visual style, linework, brush techniques, and the overall artistic presentation of the illustrations. Do not use Markdown formatting."
    prompt = f"""
    You are an experienced manga expert. Based on the following four manga titles: 【{titles_str}】.
    Please provide a fluent English recommendation of about 100 words for each. 
    Format your response strictly as follows:
    **[Manga Title]**
    [Briefly introduce the storyline, the artist’s distinctive visual style, linework, brush techniques, and the overall artistic presentation.]
    
    Ensure there is an empty line between different manga recommendations.
    Start directly with [Manga Title] and introduce the manga without any preamble or unnecessary wording. Do not include any explanations or statements about completion.
    """
    try:
        response = gemini_model.generate_content(prompt)
        return {"status": "success", "data": response.text.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail="AI 生成失敗")    

    
    
@app.get("/api/manga")
async def get_manga_list(
    genre: Optional[str] = Query(None, description="漫畫分類"), 
    page: int = Query(1, ge=1, description="頁碼"),
    limit: int = Query(100, ge=1, le=100, description="每頁數量")
):
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT)
        cursor = conn.cursor()
        offset=(page-1)*limit
        where_clause=""
        params=[]
        if genre:
            where_clause=" WHERE (labels::jsonb ->> %s)::float >=0.99"
            params.append(genre)
        count_query = f"SELECT COUNT(*) FROM anime_images {where_clause}" #算總數
        print(f"count_query目前:{count_query}")
        cursor.execute(count_query,params)
        actual_sql = cursor.query.decode('utf-8')
        print(f"真正傳入資料庫的完整 SQL: {actual_sql}")
        total_count = cursor.fetchone()[0]
        total_pages = (total_count + limit - 1) // limit if limit > 0 else 1
        
        select_query = f"SELECT manga_name, image_path, labels FROM anime_images {where_clause} ORDER BY id ASC LIMIT %s OFFSET %s"
        cursor.execute(select_query,params+[limit,offset])
        results = cursor.fetchall()
        # 封裝回傳陣列
        formatted_results = [{"manga_name": row[0], "image_path": row[1], "labels": row[2]} for row in results]
        return {
            "status": "success", 
            "data": formatted_results,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count
            }
        }
    except Exception as e:
        print(f"API 嚴重錯誤: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()    
    
# @app.get("/api/manga")
# async def get_manga_list(
#     genre: Optional[str] = Query(None, description="漫畫分類"), 
#     page: int = Query(1, ge=1, description="頁碼"),
#     limit: int = Query(100, ge=1, le=100, description="每頁數量")
# ):
#     GENRE_INDEX = {
#         "Adventure": 0, "Fantasy": 1, "Historical": 2, "Isekai": 3,
#         "Mystery": 4, "Romance": 5, "School": 6, "SF": 7,
#         "sports": 8, "Supernatural": 9
#     }
    
#     conn = None
#     cursor = None
#     try:
#         conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT)
#         cursor = conn.cursor()
        
#         # 直接拿回全部資料
#         cursor.execute("SELECT manga_name, image_path, labels FROM anime_images ORDER BY id ASC")
#         all_results = cursor.fetchall()
        
#         filtered_results = []
        
#         if genre and genre in GENRE_INDEX:
#             idx = GENRE_INDEX[genre]
            
#             # 加入計數器，只印前 3 筆避免終端機報錯
#             debug_count = 0 
            
#             for row in all_results:
#                 try:
#                     labels_data = row[2]
                    
#                     # 印出原始資料與型別
#                     if debug_count < 3:
#                         print(f"--- 偵測漫畫: {row[0]} ---", flush=True)
#                         print(f" 原始 labels: {labels_data}", flush=True) #檢查資料庫
#                         print(f" 原始型別: {type(labels_data)}", flush=True)

#                     if not labels_data:
#                         continue
                        
#                     if isinstance(labels_data, str):
#                         clean_str = labels_data.strip().replace('{', '[').replace('}', ']')
#                         if not clean_str.startswith('['):
#                             clean_str = f"[{clean_str}]"
#                         labels_list = json.loads(clean_str)
#                     else:
#                         labels_list = list(labels_data)
                    
#                     # 【印出解析後的陣列
#                     if debug_count < 3:
#                         print(f" 解析陣列: {labels_list}", flush=True)
#                         print(f" 鎖定索引 {idx} 的值: {labels_list[idx] if len(labels_list) > idx else '超出身長'}", flush=True)
#                         debug_count += 1
                        
#                     if len(labels_list) > idx and float(labels_list[idx]) >= 0.99:
#                         filtered_results.append(row)
                        
#                 except Exception as row_error:
#                     # 【觀測站 3】：印出錯誤
#                     if debug_count < 5:
#                         print(f" 解析崩: {row_error} (原始資料: {row[2]})", flush=True)
#                         debug_count += 1
#                     continue
#         else:
#             filtered_results = all_results
            
#         # 記憶體分頁計算
#         total_count = len(filtered_results)
#         total_pages = (total_count + limit - 1) // limit if limit > 0 else 1
#         offset = (page - 1) * limit
#         page_results = filtered_results[offset : offset + limit]
        
#         formatted_results = []
#         for row in page_results:
#             formatted_results.append({
#                 "manga_name": row[0],
#                 "image_path": row[1],
#                 "labels": row[2]
#             })
            
#         return {
#             "status": "success", 
#             "data": formatted_results,
#             "pagination": {
#                 "current_page": page,
#                 "total_pages": total_pages,
#                 "total_count": total_count
#             }
#         }
#     except Exception as e:
#         # 萬一資料庫連線出包，印出強烈警告
#         print(f"API 嚴重錯誤: {str(e)}", flush=True)
#         raise HTTPException(status_code=500, detail=str(e))
#     finally:
#         # 確保連線安全關閉
#         if cursor is not None:
#             cursor.close()
#         if conn is not None:
#             conn.close()
            
            