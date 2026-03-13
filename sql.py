import os
import torch
import torch.nn as nn
import torchvision.models as models
import torchvision.transforms as transforms
from PIL import Image
import pandas as pd
import psycopg2
from pgvector.psycopg2 import register_vector
import json
from dotenv import load_dotenv
load_dotenv()

DB_HOST = "db"        # 直接指向 docker-compose 裡的 db 服務名稱
DB_NAME = "manhwa"
DB_USER = "postgres"
DB_PASS = os.environ.get("POSTGRES_ROOT_PASSWORD")
DB_PORT = 5432
# 1. 系統組態與資料庫連線

# DB_HOST = "host.docker.internal" # 如果 PostgreSQL 架在 Windows 本機，Docker 內要用這個 IP 才能連到外面
# DB_NAME = "manhwa"
# DB_USER = "postgres"
# DB_PASS = ""        # 請替換成你的資料庫密碼
# DB_PORT = ""

try:
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT)
    # 註冊 pgvector 型別，讓 Python 陣列能無縫轉換為 SQL 向量
    register_vector(conn)
    cursor = conn.cursor()
    
    cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS anime_images (
        id SERIAL PRIMARY KEY,
        manga_name VARCHAR(255),
        image_path TEXT UNIQUE,
        labels JSONB,
        semantic_feature vector(512), 
        style_feature vector(1536)
    );
    """
    cursor.execute(create_table_sql)
    conn.commit()
    register_vector(conn)
    print(">>> PostgreSQL 資料庫連線與自動建表初始化成功！")
    
except Exception as e:
    print(f"資料庫連線失敗: {e}")
    exit(1)


# 2. 雙輸出特徵引擎架構 (與你之前測試的一模一樣)

def calc_gram_matrix(feature_map):
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
        self.avgpool = self.base_model.avgpool

    def forward(self, x):
        f1 = self.layer1(x)
        g1 = calc_gram_matrix(f1) 
        f2 = self.layer2(f1)
        g2 = calc_gram_matrix(f2) 
        f3 = self.layer3(f2)
        g3 = calc_gram_matrix(f3) 
        
        g1_pooled = torch.max(g1, dim=2)[0]
        g2_pooled = torch.max(g2, dim=2)[0]
        g3_pooled = torch.max(g3, dim=2)[0]
        
        e_sty = torch.cat((g1_pooled, g2_pooled, g3_pooled), dim=1)
        
        f4 = self.layer4(f3)
        e_sem = self.avgpool(f4)
        e_sem = torch.flatten(e_sem, 1) 
        
        return e_sem, e_sty


# 3. 喚醒模型與載入記憶

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
base_model = models.resnet18(weights=None)
base_model.fc = nn.Linear(base_model.fc.in_features, 10)
base_model.load_state_dict(torch.load("multi_label_model_epoch_4.pth", map_location=device))

encoder = DualOutputEncoder(base_model).to(device)
encoder.eval()

transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.6272, 0.5589, 0.5401], std=[0.3236, 0.3215, 0.3189])
])


# 4. ETL 批次處理管線

print(">>> 開始讀取 labels.csv...")
df_labels = pd.read_csv("labels.csv")
classes = df_labels.columns[1:].tolist()

total_images = len(df_labels)
success_count = 0

print(f">>> 啟動 ETL 寫入程序，共計 {total_images} 張圖片待處理...")

for index, row in df_labels.iterrows():
    full_image_path = row.iloc[0] # 例如: ./images/Adventure/Naruto_123.jpg
    
    # [轉換 1] 萃取相對路徑與漫畫名稱
    # 移除前面的 "./images/" 以取得相對路徑
    relative_path = full_image_path.replace("./images/", "").replace(".\\images\\", "") 
    filename = os.path.basename(full_image_path)
    # 利用 rsplit 從右邊切開底線，精準抓出 "_918.jpg" 前面的漫畫名稱
    manga_name = filename.rsplit('_', 1)[0] 
    
    # [轉換 2] 將 10 個標籤轉為 JSON 格式
    label_dict = {classes[i]: float(row.iloc[i+1]) for i in range(len(classes))}
    label_json = json.dumps(label_dict)
    
    try:
        # [轉換 3] 進入神經網路榨取特徵
        image = Image.open(full_image_path).convert('RGB')
        input_tensor = transform(image).unsqueeze(0).to(device)
        
        with torch.no_grad():
            e_sem, e_sty = encoder(input_tensor)
        
        # 將 PyTorch Tensor 轉為標準 Python List
        sem_vector = e_sem[0].cpu().numpy()
        sty_vector = e_sty[0].cpu().numpy()
        
        # [載入 4] 寫入 PostgreSQL
        # 使用 ON CONFLICT DO NOTHING 防呆機制：如果 image_path 已經存在，就跳過不寫入
        sql = """
            INSERT INTO anime_images (manga_name, image_path, labels, semantic_feature, style_feature)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (image_path) DO NOTHING;
        """
        cursor.execute(sql, (manga_name, relative_path, label_json, sem_vector, sty_vector))
        
        success_count += 1
        
        # 每處理 100 張就提交一次交易，並印出進度
        if success_count % 100 == 0:
            conn.commit()
            print(f"  - 進度: {success_count} / {total_images} 處理完成...")
            
    except Exception as e:
        print(f"處理圖片 {relative_path} 時發生錯誤: {e}")
        conn.rollback() # 發生錯誤時退回當前交易，避免資料庫鎖死

# 最後提交剩餘的資料
conn.commit()
cursor.close()
conn.close()

print(f"\n>>>  ETL 任務圓滿結束！成功將 {success_count} 筆高維度特徵寫入 PostgreSQL。")