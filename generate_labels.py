import os
import hashlib
import pandas as pd

def get_image_md5(file_path):
    """計算實體檔案的 MD5 數位指紋"""
    hash_md5 = hashlib.md5()
    # 以二進制讀取，每次讀取 4096 bytes，避免記憶體爆掉
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

# 基礎設定
base_dir = "./images"
# 這是你截圖中的 10 個類別 (請確保大小寫與資料夾名稱完全一致)
categories = ['Adventure', 'Fantasy', 'Historical', 'Isekai', 'Mystery', 
              'Romance', 'School', 'SF', 'sports', 'Supernatural']

# 存放結果的字典 (Key: MD5指紋, Value: {image_path, Adventure:1, Fantasy:0...})
unique_images_registry = {}

print(">>> 啟動資料清理與標籤生成引擎...")

# 遍歷所有資料夾
for category in categories:
    folder_path = os.path.join(base_dir, category)
    if not os.path.exists(folder_path):
        print(f"警告: 找不到資料夾 {folder_path}")
        continue
        
    print(f"正在掃描 [{category}] 資料夾...")
    for filename in os.listdir(folder_path):
        # 只處理圖片檔
        if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            file_path = os.path.join(folder_path, filename)
            
            # 1. 萃取數位指紋
            file_hash = get_image_md5(file_path)
            
            # 2. 如果是第一次看到這張圖，建立初始化結構
            if file_hash not in unique_images_registry:
                unique_images_registry[file_hash] = {'image_path': file_path}
                # 將所有畫風先預設為 0
                for c in categories:
                    unique_images_registry[file_hash][c] = 0.0
            
            # 3. 核心邏輯：無論是不是第一次看到，都把這個資料夾代表的畫風標記為 1.0
            unique_images_registry[file_hash][category] = 1.0

# 將字典轉換為 Pandas 表格
df = pd.DataFrame(list(unique_images_registry.values()))

# 輸出統計數據
total_physical_files = sum([len(files) for r, d, files in os.walk(base_dir)])
unique_files_count = len(df)
duplicate_count = total_physical_files - unique_files_count

print("\n" + "="*40)
print(f"📊 資料庫掃描報告：")
print(f" - 掃描到的實體圖片總數: {total_physical_files}")
print(f" - 實際獨立圖片總數 (去重後): {unique_files_count}")
print(f" - 發現並成功合併的重複圖片: {duplicate_count} 張")
print("="*40)

# 將結果儲存成 CSV 檔案
output_csv = "labels.csv"
df.to_csv(output_csv, index=False)
print(f"\n>>> 成功！多標籤矩陣已輸出至 {output_csv}")