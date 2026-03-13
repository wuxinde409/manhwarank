import torch
import torch.nn as nn
import torchvision.models as models
import torchvision.transforms as transforms
from PIL import Image

# ==========================================
# 1. 你已經寫好的雙輸出引擎架構
# ==========================================
def calc_gram_matrix(feature_map):
    b, c, h, w = feature_map.size()
    features = feature_map.view(b, c, h * w) 
    G = torch.bmm(features, features.transpose(1, 2)) 
    return G.div(h * w)

class DualOutputEncoder(nn.Module):
    def __init__(self, fine_tuned_resnet):
        super(DualOutputEncoder, self).__init__()
        self.base_model = fine_tuned_resnet
        self.base_model.fc = nn.Identity() # 斷頭手術
        
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

# ==========================================
# 2. 喚醒程序：載入權重並組裝引擎
# ==========================================
print(">>> 正在準備特徵萃取引擎...")
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

# 步驟 A: 蓋出原本的大腦結構 (必須跟訓練時一模一樣，包含 10 個輸出的 fc 層)
base_model = models.resnet18(weights=None)
num_ftrs = base_model.fc.in_features
base_model.fc = nn.Linear(num_ftrs, 10)

# 步驟 B: 載入第 4 輪的最強記憶 (請確保檔名與路徑正確)
weights_path = "multi_label_model_epoch_4.pth"
base_model.load_state_dict(torch.load(weights_path, map_location=device))

# 步驟 C: 送上手術台改裝為雙輸出引擎，並設定為 eval 評估模式 (關閉梯度計算)
encoder = DualOutputEncoder(base_model).to(device)
encoder.eval()

# ==========================================
# 3. 餵入照片與特徵解析
# ==========================================
# 必須使用跟訓練時「完全相同」的測試前置處理邏輯
transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.6272, 0.5589, 0.5401], std=[0.3236, 0.3215, 0.3189])
])

# 請在這裡填入你想測試的任何一張照片路徑
test_image_path = "./images/Adventure/Ore Igai Daremo Saishu Dekinai Sozai nanoni Sozai Saishuritsu ga Hikui to Power Harassment suru Osananajimi Renkinjutsushi to Zetsuen shita Senzoku Madoushi Henkyou no Machi de Slow Life wo Okuritai_918.jpg"

try:
    image = Image.open(test_image_path).convert('RGB')
    
    # 物理意義：圖片原本是 [3, 224, 224]，但模型吃的是批次，所以要加上 unsqueeze(0) 變成 [1, 3, 224, 224]
    input_tensor = transform(image).unsqueeze(0).to(device)
    
    # 進行推論 (不計算梯度，節省記憶體)
    with torch.no_grad():
        e_sem, e_sty = encoder(input_tensor)
        
    print("\n>>> extract成功！開始解析：")
    print(f" - 語意特徵 (Semantic) 維度大小: {e_sem.shape}")
    print(f" - 風格特徵 (Style) 維度大小: {e_sty.shape}")
    
    # 印出特徵向量的前五個浮點數看看長怎樣
    print(f"\n[語意特徵數值預覽]: {e_sem[0][:5].tolist()} ...")
    print(f"[風格特徵數值預覽]: {e_sty[0][:5].tolist()} ...")

except Exception as e:
    print(f"讀取圖片或推論時發生錯誤: {e}")