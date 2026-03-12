import torch 
import os
import torchvision.transforms as transforms
from torch.utils.data import DataLoader, random_split, Dataset
import pandas as pd
from PIL import Image
import copy
import torch.nn as nn
import torch.optim as optim
import torchvision.models as models

# 1. 多標籤專屬資料讀取引擎 (Multi-label Dataset)

class MultiLabelAnimeDataset(Dataset):
    def __init__(self, csv_file, transform=None):
        self.data_frame = pd.read_csv(csv_file)
        self.transform = transform
        self.classes = self.data_frame.columns[1:].tolist()

    def __len__(self):
        return len(self.data_frame)

    def __getitem__(self, idx):
        img_path = self.data_frame.iloc[idx, 0]
        image = Image.open(img_path).convert('RGB')

        if self.transform:
            image = self.transform(image)

        # 抓取 10 個畫風標籤，轉成 BCE Loss 規定的 Float32 張量
        labels = self.data_frame.iloc[idx, 1:].values.astype(float)
        labels = torch.tensor(labels, dtype=torch.float32)

        return image, labels


# 2. (Data Augmentation)

train_transforms = transforms.Compose([
    transforms.RandomResizedCrop(224, scale=(0.8, 1.0)),
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomRotation(degrees=15),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.6272, 0.5589, 0.5401], std=[0.3236, 0.3215, 0.3189])
])

test_transforms = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.6272, 0.5589, 0.5401], std=[0.3236, 0.3215, 0.3189])
])

# 實體化 Dataset 並讀取剛剛生成的 labels.csv
full_dataset = MultiLabelAnimeDataset(csv_file="labels.csv", transform=test_transforms)
print(f">>> 成功載入多標籤引擎，畫風類別: {full_dataset.classes}")

# 資料集切割 (80% Train, 10% Val, 10% Test)
train_size = int(0.8 * len(full_dataset))
val_size = int(0.1 * len(full_dataset))
test_size = len(full_dataset) - train_size - val_size

train_dataset, val_dataset, test_dataset = random_split(
    full_dataset, [train_size, val_size, test_size], generator=torch.Generator().manual_seed(42)
)

# 為 Train Dataset 抽換成擴增版本的 Transform
train_dataset.dataset = copy.copy(full_dataset)
train_dataset.dataset.transform = train_transforms

batch_size = 32
train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=2)
val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=2)
test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False, num_workers=2)


# 神經網路架構與硬體分配

device = torch.device("cuda:0")
print(f">>> 目前實際分配到的運算設備: {device}")

# 載入預訓練大腦 (17層舊記憶)
# model = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
model = models.resnet18(weights=None)
num_ftrs = model.fc.in_features
# 換上全新的第 18 層 (10 個獨立輸出的神經元)
model.fc = nn.Linear(num_ftrs, 10)
model = model.to(device)

# 多選題專屬計分板與設定
criterion = nn.BCEWithLogitsLoss()
optimizer = optim.Adam(model.parameters(), lr=0.0003)
scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=10, gamma=0.5)


# 4(Training Loop)

num_epoches = 50
top5_models = []

print(">>> 訓練正式開始")
for epoch in range(num_epoches):
    model.train()
    running_loss = 0.0
    correct_train = 0
    total_train = 0
    
    for images, labels in train_loader:
        images, labels = images.to(device), labels.to(device)
        
        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()
        
        running_loss += loss.item()
        
        # 多標籤預測邏輯：獨立轉成機率，超過 50% 視為猜測存在
        predicted_probs = torch.sigmoid(outputs)
        predicted = (predicted_probs > 0.5).float()
        
        # 總計分格數為 batch_size * 10 
        total_train += labels.numel()
        correct_train += (predicted == labels).sum().item()
            
    train_loss = running_loss / len(train_loader)
    train_acc = 100 * correct_train / total_train

    #  驗證階段 (Validation)
    model.eval()
    val_loss = 0.0
    correct_val = 0
    total_val = 0
    
    with torch.no_grad():
        for images, labels in val_loader:
            images, labels = images.to(device), labels.to(device)
            
            outputs = model(images)
            loss = criterion(outputs, labels)
            
            val_loss += loss.item()
            
            predicted_probs = torch.sigmoid(outputs.data)
            predicted = (predicted_probs > 0.5).float()
            
            total_val += labels.numel()
            correct_val += (predicted == labels).sum().item()
            
    val_loss = val_loss / len(val_loader)
    val_acc = 100 * correct_val / total_val
    
    # 印出基礎
    print(f"Epoch [{epoch+1}/{num_epoches}] "
          f"Train Loss: {train_loss:.4f}, Train Acc: {train_acc:.2f}% | "
          f"Val Loss: {val_loss:.4f}, Val Acc: {val_acc:.2f}%")
    
  
    # 6. Top-5備份

    if len(top5_models) < 5 or val_acc > top5_models[-1][0]:
        current_model_path = f"multi_label_model_epoch_{epoch+1}.pth"
        torch.save(model.state_dict(), current_model_path)
        
        top5_models.append((val_acc, epoch+1, current_model_path, train_loss, train_acc, val_loss))
        top5_models.sort(key=lambda x: x[0], reverse=True)
        
        if len(top5_models) > 5:
            _, _, path_to_remove, _, _, _ = top5_models.pop()
            if os.path.exists(path_to_remove):
                os.remove(path_to_remove)
        
        print(f"  >>>  成功進入前五名！已儲存至 {current_model_path}")
        print("  >>>  目前 Top 5 :")
        for rank, m in enumerate(top5_models, 1):
            print(f"      第 {rank} 名 - Epoch [{m[1]}/{num_epoches}] "
                  f"Train Loss: {m[3]:.4f}, Train Acc: {m[4]:.2f}% | "
                  f"Val Loss: {m[5]:.4f}, Val Acc: {m[0]:.2f}%")
                  
    # 排程器步進更新
    scheduler.step()