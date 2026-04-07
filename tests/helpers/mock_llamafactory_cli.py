from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "train":
        print("usage: mock_llamafactory_cli.py train <config_path>", file=sys.stderr)
        return 2

    config_path = Path(argv[2]).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise RuntimeError(f"invalid config payload: {config_path}")

    dataset_dir = Path(str(config.get("dataset_dir") or "")).resolve()
    dataset_info_path = Path(str(config.get("dataset_info_path") or dataset_dir / "dataset_info.json")).resolve()
    output_dir = Path(str(config.get("output_dir") or "")).resolve()
    dataset_name = str(config.get("dataset") or "")
    epoch_count = max(1, int(config.get("num_train_epochs") or 3))
    learning_rate = float(config.get("learning_rate") or 1e-4)

    if not dataset_dir.exists():
        raise RuntimeError(f"dataset_dir does not exist: {dataset_dir}")
    if not dataset_info_path.exists():
        raise RuntimeError(f"dataset_info_path does not exist: {dataset_info_path}")

    dataset_info = json.loads(dataset_info_path.read_text(encoding="utf-8"))
    if dataset_name not in dataset_info:
        raise RuntimeError(f"dataset {dataset_name!r} not found in {dataset_info_path}")

    dataset_file = dataset_dir / str(dataset_info[dataset_name]["file_name"])
    if not dataset_file.exists():
        raise RuntimeError(f"dataset file does not exist: {dataset_file}")

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"dataset={dataset_file.as_posix()}", flush=True)
    print(f"output_dir={output_dir.as_posix()}", flush=True)

    history: list[dict[str, float]] = []
    for epoch in range(1, epoch_count + 1):
        loss = round(0.75 / (epoch + 0.5), 4)
        point = {
            "step": float(epoch),
            "epoch": float(epoch),
            "learning_rate": learning_rate,
            "loss": loss,
        }
        history.append(point)
        print(json.dumps(point, ensure_ascii=False), flush=True)
        print(f"Epoch {epoch}/{epoch_count} | loss: {loss:.4f} | lr: {learning_rate:.6f}", flush=True)
        time.sleep(0.05)

    (output_dir / "adapter_config.json").write_text(
        json.dumps(
            {
                "base_model": config.get("model_name_or_path"),
                "peft_type": "LORA",
                "r": 8,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "adapter_model.safetensors").write_text("mock-weights\n", encoding="utf-8")
    (output_dir / "trainer_state.json").write_text(
        json.dumps({"log_history": history}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("train completed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
