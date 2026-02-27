# 自动标注系统（开发中）

本仓库是一个**单机单用户**的自动标注闭环系统：图片上传 → 自动标注（检测/可选分割）→ 人工纠错 →（可选）微调/评估。

- 技术路线与目标见 `design_doc.md`
- 可执行的开发计划与进度见 `dev_plan.md`

## 快速开始（开发）

### 后端（FastAPI）

1) 安装依赖（建议使用虚拟环境）

```powershell
python -m venv .venv
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
```

2) 启动

```powershell
python -m backend.main
```

健康检查：`GET http://127.0.0.1:8000/healthz`

### 前端（Vue + Vite）

```powershell
cd frontend
npm install
npm run dev
```

默认前端地址：`http://localhost:5173`

---

## 约定

- 本地数据默认写入 `data/`（不会提交到 git）
- 里程碑采用“提交 + 自动验证 + 人工验收”节奏推进

