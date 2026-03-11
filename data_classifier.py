import torch 
import os
import torchvision
import torchvision.transforms as transforms
from torch.utils.data import DataLoader, random_split
from torchvision.datasets import ImageFolder
import copy
import torch.nn as nn
import torch.optim as optim
import torchvision.models as models

#這邊要先配合data argumentation來建構train dataset
train_transforms = transforms.Compose([
    transforms.RandomResizedCrop(224,scale=(0.8,1.0)),
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomRotation(degrees=15),
    transforms.ToTensor(), #準備正規化
    transforms.Normalize(mean=[0.6272114515304565, 0.5589821934700012, 0.5401213765144348],std=[0.32363271713256836, 0.32153722643852234, 0.3189696669578552])
    
])
#這邊開始製作test dataset
test_transforms = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.6272114515304565, 0.5589821934700012, 0.5401213765144348],std=[0.32363271713256836, 0.32153722643852234, 0.3189696669578552])
    
])
full_dataset = ImageFolder(root="./images", transform=test_transforms)
train_size= int(0.8*len(full_dataset))
val_size= int(0.1*len(full_dataset))
test_size= len(full_dataset) - train_size - val_size

train_dataset, val_dataset, test_dataset = random_split(full_dataset,[train_size, val_size, test_size],generator=torch.Generator().manual_seed(42))
train_dataset.dataset = copy.copy(full_dataset) #train_dataset 的源頭拷貝一份，並抽換為擴增版本的 transform
train_dataset.dataset.transform = train_transforms

batch_size=32 #每次抓的量
train_loader = DataLoader(train_dataset,batch_size,shuffle=True, num_workers=2)
val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=2)
test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False, num_workers=2)

print(f"成功抓取到的畫風類別: {full_dataset.classes}")

device= torch.device("cuda:0") #選gpu
model= models.resnet18(weights=None) # 套上resnet18 model
num_ftrs= model.fc.in_features #這便是在做transefer learing?
model.fc= nn.Linear(num_ftrs,10) # 這東西model.fc 指的是 model 最後一層Fully Connected Layer
model=model.to(device) #讓我們gpu去跑他

criterion = nn.CrossEntropyLoss() #設定loss
optimizer = optim.Adam(model.parameters(), lr=0.001)

num_epoches=100 #訓練50次
top5_models = []
best_val_arr=0
best_model_path = "best_anime_style_model.pth"
print("訓練開始")
for epoch in range(num_epoches):
    model.train()
    running_loss=0.0
    correct_train=0
    total_train=0
    for images, labels in train_loader :
        images, labels = images.to(device), labels.to(device)
        optimizer.zero_grad() # 清空舊梯度
        outputs=model(images) # 進行正向傳播:輸入進去 最後經過model跑出的結果
        loss=criterion(outputs,labels)
        loss.backward() # 反向傳播
        optimizer.step() #更新權重
        running_loss+=loss.item()
        _, predicted = torch.max(outputs,1)
        total_train+=labels.size(0) #目前train的總數量
        correct_train += (predicted == labels).sum().item() #把32個值裡面有對的用.sum 加起來, 配合.item取出
            
    train_loss = running_loss / len(train_loader)
    train_acc = 100 * correct_train / total_train

    # ========================
    # 驗證階段 (Validation Phase)
    # ========================
    model.eval() # 告訴 PyTorch 模型進入評估模式 (關閉 Dropout 等干擾)
    val_loss = 0.0
    correct_val = 0
    total_val = 0
    
    # torch.no_grad() 非常重要：它會關閉梯度計算，大幅節省記憶體與運算時間
    with torch.no_grad():
        for images, labels in val_loader:
            images = images.to(device)
            labels = labels.to(device)
            
            outputs = model(images)
            loss = criterion(outputs, labels)
            
            val_loss += loss.item()
            _, predicted = torch.max(outputs.data, 1)
            total_val += labels.size(0)  #這邊是表示你要會傳一個等同batch_size數量相同的label回去, 但他在pytorch被視為1維,所以用.size(0)去取
            correct_val += (predicted == labels).sum().item()
            
    val_loss = val_loss / len(val_loader)
    val_acc = 100 * correct_val / total_val
    
    # 印出每一個 Epoch 的表現
    print(f"目前在第 :Epoch [{epoch+1}/{num_epoches}] "
        f"Train Loss: {train_loss:.4f}, Train Acc: {train_acc:.2f}% | "
        f"Val Loss: {val_loss:.4f}, Val Acc: {val_acc:.2f}%")
    
    if len(top5_models) < 5 or val_acc > top5_models[-1][0]:
            
            current_model_path = f"anime_style_model_epoch_{epoch+1}.pth"
            torch.save(model.state_dict(), current_model_path)
            
            # 【修改點 1】：把你想看的所有指標，全部打包塞進這個陣列紀錄中
            top5_models.append((val_acc, epoch+1, current_model_path, train_loss, train_acc, val_loss))
            
            # 重新排名 (根據 val_acc，依然是 index 0)
            top5_models.sort(key=lambda x: x[0], reverse=True)
            
            # 資源回收：踢掉第 6 名並刪除硬碟檔案
            if len(top5_models) > 5:
                # _, _, path_to_remove, _, _, _ 代表我們只在乎把第三個位置的檔名抓出來刪除
                _, _, path_to_remove, _, _, _ = top5_models.pop()
                if os.path.exists(path_to_remove):
                    os.remove(path_to_remove)
            
            # 【修改點 2】：用你指定的格式，印出華麗且詳盡的 Top 5 榜單
            print(f" >>>  成功進入前五進榜！已儲存至 {current_model_path}")
            print("  >>>  目前 Top 5 榜單:")
            
            # 用 for 迴圈逐行印出這 5 名的完整健康報告
            for rank, m in enumerate(top5_models, 1):
                # m 的結構是: (val_acc[0], epoch[1], 檔名[2], train_loss[3], train_acc[4], val_loss[5])
                print(f"      第 {rank} 名 - Epoch [{m[1]}/{num_epoches}] "
                    f"Train Loss: {m[3]:.4f}, Train Acc: {m[4]:.2f}% | "
                    f"Val Loss: {m[5]:.4f}, Val Acc: {m[0]:.2f}%")