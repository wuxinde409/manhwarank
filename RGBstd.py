import torch
import torchvision.transforms as transforms
from torchvision.datasets import ImageFolder
from torch.utils.data import DataLoader

# 1. 這裡只需要轉成 Tensor，不需要 Normalize
basic_transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor()
])

# 2. 載入你的 10,000 張圖片
dataset = ImageFolder(root='./images', transform=basic_transform)
loader = DataLoader(dataset, batch_size=64, shuffle=False, num_workers=0)

def get_mean_and_std(dataloader):
    channels_sum, channels_squared_sum, num_batches = 0, 0, 0
    
    print("開始計算資料集 RGB 平均值與標準差，請稍候...")
    for data, _ in dataloader:
        # data 的維度是 [batch_size, channels, height, width]
        channels_sum += torch.mean(data, dim=[0, 2, 3])
        channels_squared_sum += torch.mean(data**2, dim=[0, 2, 3])
        num_batches += 1
    
    mean = channels_sum / num_batches
    std = (channels_squared_sum / num_batches - mean**2)**0.5
    return mean, std

mean, std = get_mean_and_std(loader)
print(f"專屬 Mean: {mean.tolist()}")
print(f"專屬 Std:  {std.tolist()}")