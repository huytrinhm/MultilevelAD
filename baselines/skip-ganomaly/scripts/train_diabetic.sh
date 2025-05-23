#!/usr/bin/env bash
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

source ~/miniconda3/etc/profile.d/conda.sh
conda activate skipganomaly

DATASETS=("diabetic")

MODEL_DATA_DIR="./data_diabetic"
MODEL_NORMAL_CLASS="0.normal"
MODEL_ABNORMAL_CLASS="1.abnormal"

for DATASET_NAME in "${DATASETS[@]}"
do
echo "Training on dataset: $DATASET_NAME"

DATASET_DIR="$(pwd)/../../data/Medical/diabetic-retinopathy"

rm -rf "$MODEL_DATA_DIR"
mkdir -p "$MODEL_DATA_DIR/train/$"
mkdir -p "$MODEL_DATA_DIR/test/$MODEL_NORMAL_CLASS"
mkdir -p "$MODEL_DATA_DIR/test/$MODEL_ABNORMAL_CLASS"

ln -sn "$DATASET_DIR/level_0_train" "$MODEL_DATA_DIR/train/$MODEL_NORMAL_CLASS"

find "$DATASET_DIR/level_0_test" -maxdepth 1 -type f | sort | head -n 50 | while IFS= read -r file; do
  ln -sn "$file" "$MODEL_DATA_DIR/test/$MODEL_NORMAL_CLASS/$(basename "$file")"
done

find "$DATASET_DIR/level_1" -maxdepth 1 -type f | sort | head -n 50 | while IFS= read -r file; do
  ln -sn "$file" "$MODEL_DATA_DIR/test/$MODEL_ABNORMAL_CLASS/$(basename "$file")"
done

CUDA_VISIBLE_DEVICES=5 python train.py \
    --model skipganomaly \
    --dataset $DATASET_NAME \
    --dataroot "./data_diabetic" \
    --isize 32 \
    --niter 50 \
    --outf "./output_diabetic/" \
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
