import os
data_dir = 'data'
if os.path.exists(data_dir):
    print(os.listdir(data_dir))
else:
    print("data dir not found")