import torch 
import torchvision
import torchvision.transforms as transforms
from torch.utils.data import DataLoader, random_split
from torchvision.datasets import ImageFolder
import copy

#這邊要先配合data argumentation來建構train dataset
train_transforms = transforms.Compose([
    transforms.RandomCrop(224,scale=(0.8,1.0)),
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomRotation(degrees=15),
    transforms.ToTensor(), #準備正規化
    transforms.Normalize(mean=,std=)
    
])
#這邊開始製作test dataset
test_transforms = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.Totensor(),
    transforms.Normalize(mean=,std=)
    
])