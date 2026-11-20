import os, shutil

images_dir = "images"
labels_dir = "labels"
classes_file = "classes.txt"
out = "yolo_cvat"
data_dir = os.path.join(out, "obj_train_data")
os.makedirs(data_dir, exist_ok=True)

# copy ảnh + label vào chung 1 thư mục
img_list = []
for f in sorted(os.listdir(images_dir)):
    if f.lower().endswith((".jpg", ".jpeg", ".png")):
        name = os.path.splitext(f)[0]
        shutil.copy(os.path.join(images_dir, f), data_dir)
        lbl = os.path.join(labels_dir, name + ".txt")
        if os.path.exists(lbl):
            shutil.copy(lbl, data_dir)
        img_list.append(f"data/obj_train_data/{f}")

# obj.names
shutil.copy(classes_file, os.path.join(out, "obj.names"))
n_classes = len([l for l in open(classes_file) if l.strip()])

# obj.data
with open(os.path.join(out, "obj.data"), "w") as f:
    f.write(f"classes = {n_classes}\n")
    f.write("train = data/train.txt\n")
    f.write("names = data/obj.names\n")
    f.write("train_data_dir = data/obj_train_data\n")

# train.txt
with open(os.path.join(out, "train.txt"), "w") as f:
    f.write("\n".join(img_list))

# nén zip
shutil.make_archive("yolo_cvat", "zip", out)
print("Xong: yolo_cvat.zip")