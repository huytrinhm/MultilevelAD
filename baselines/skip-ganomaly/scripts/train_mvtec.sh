#!/usr/bin/env bash
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

source ~/miniconda3/etc/profile.d/conda.sh
conda activate skipganomaly

DATASETS=("bottle" "carpet" "grid" "leather" "tile" "wood" "cable" "capsule" "hazelnut" "metal_nut" "pill" "screw" "transistor" "zipper")

for DATASET_NAME in "${DATASETS[@]}"
do
echo "Training on dataset: $DATASET_NAME"

DATASET_DIR="$(pwd)/../../data/Industry/mvtec/$DATASET_NAME"

rm -rf './data_mvtec/'
mkdir -p "./data_mvtec/train/"
mkdir -p "./data_mvtec/test/1.abnormal"

ln -sn "$DATASET_DIR/train/good" "./data_mvtec/train/0.normal"
ln -sn "$DATASET_DIR/test/good" "./data_mvtec/test/0.normal"

# Process all other subdirectories of test
for subdir in "$DATASET_DIR/test"/*; do
  if [ -d "$subdir" ] && [ "$(basename "$subdir")" != "good" ]; then
    subdir_name=$(basename "$subdir")

    # Process each file in the subdirectory
    for file in "$subdir"/*; do
      if [ -f "$file" ]; then
        ln -sn "$file" "./data_mvtec/test/1.abnormal/${subdir_name}_$(basename "$file")"
      fi
    done
  fi
done

CUDA_VISIBLE_DEVICES=7 python train.py \
    --model skipganomaly \
    --dataset $DATASET_NAME \
    --dataroot "./data_mvtec" \
    --isize 32 \
    --niter 50 \
    --outf "./output_mvtec" \
    --manualseed 1
    # --save_image_freq 5
    # --save_test_images \
    # --workers 8 \
    # --nc 3 \
    # --device gpu \
    # --outf "$(pwd)/output" \
    # --beta1 0.5 \
    # --w_adv 1 \
    # --w_con 50 \
    # --w_lat 1
done
