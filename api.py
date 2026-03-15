import os
import io
import json
import torch
import torch.nn as nn
import torchvision.models as models
import torchvision.transforms as transforms
from PIL import Image
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
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
load_dotenv()
DB_HOST = "db"
DB_NAME = "manhwa"
DB_USER = "postgres"
DB_PASS = os.environ.get("POSTGRES_ROOT_PASSWORD")
DB_PORT = 5432

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
async def search_similar_manga(request: Request, file: UploadFile=File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid file type. Only images are allowed.")
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        
        input_tensor = transform(image).unsqueeze(0).to(device)
        with torch.no_grad():
            e_sem, e_sey= encoder(input_tensor)
        sem_vector =e_sem[0].cpu().numpy().tolist()
        
        #資料庫
        conn=psycopg2.connect(host=DB_HOST,database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT)
        register_vector(conn)
        cursor=conn.cursor() #生成物件去控制database
        
        search_query = '''
            SELECT manga_name, image_path, labels, (semantic_feature <=> %s) AS distance
            FROM anime_images
            WHERE (semantic_feature <=> %s) > 0.01
            ORDER BY distance ASC
            LIMIT 5;
        '''
        # cursor.execute(search_query,(str(sem_vector),))
        cursor.execute(search_query, (str(sem_vector), str(sem_vector)))
        results=cursor.fetchall()
        formatted_results =[] #裝回傳資料用的
        for row in results :
            formatted_results.append({
                "manga_name": row[0],
                "image_path": row[1],
                "similarity_score": round(1-float(row[3]), 4),
                "labels":row[2]
            })
        cursor.close()
        conn.close()
        return {"status": "success", "data": formatted_results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")