import os
import re

def clean_duplicate_images(folder_path):
    # 防呆檢查：確認資料夾是否存在
    if not os.path.exists(folder_path):
        print(f" 找不到資料夾：{folder_path}")
        return

    # 建立正規表示式規則：匹配 "任何字元" + "_" + "3位數字" + ".jpg/png/webp"
    # 例如它可以精準抓出 "Yuusha Yamemasu" 以及後面的 "272"
    pattern = re.compile(r"^(.*)_(\d{3})\.(jpg|jpeg|png|webp)$", re.IGNORECASE)
    
    # 用來記憶「已經保留過」的漫畫名稱
    seen_titles = set()
    removed_count = 0

    print(f" 開始掃描資料夾：{folder_path}/ ...\n")

    for filename in os.listdir(folder_path):
        filepath = os.path.join(folder_path, filename)

        # 確保只處理檔案，不處理子資料夾
        if os.path.isfile(filepath):
            match = pattern.match(filename)
            
            # 如果檔名符合我們的爬蟲命名規則
            if match:
                base_title = match.group(1) # 取得底線前面的真實漫畫名稱 (例: Yuusha Yamemasu)
                
                if base_title in seen_titles:
                    # 如果這個名字已經在記憶清單中，代表這是重複的，將其刪除
                    print(f" 發現重複圖片，正在刪除: {filename}")
                    os.remove(filepath)
                    removed_count += 1
                else:
                    # 如果是第一次看到這個名字，把它加入記憶清單，並保留檔案
                    seen_titles.add(base_title)
                    # print(f" 保留首張圖片: {filename}") # 可取消註解來查看保留清單

    print("-" * 50)
    print(f"清理完成！共刪除了 {removed_count} 張重複圖片。")
    print(f"目前資料夾內剩下 {len(seen_titles)} 張唯一圖片。")

if __name__ == "__main__":
    try:
        # 讓使用者輸入要清理的資料夾名稱
        target_folder = ""
        while not target_folder:
            target_folder = input("\n請輸入要清理的資料夾名稱 (例如 romance, action) : ").strip()
            
        clean_duplicate_images(target_folder)
        
    except KeyboardInterrupt:
        print("\n\n 收到強制終止指令 (Ctrl+C)！")