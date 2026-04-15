import { motion } from 'framer-motion'
import { useEffect, useState } from 'react'

import { api } from '../api'
import type { SystemConfigPayload, SystemSettingsPayload } from '../types'

type SystemPageProps = {
  pushToast: (message: string, tone?: 'success' | 'danger' | 'info') => void
}

export function SystemPage({ pushToast }: SystemPageProps) {
  const [config, setConfig] = useState<SystemConfigPayload | null>(null)
  const [draft, setDraft] = useState<SystemSettingsPayload | null>(null)

  const load = async () => {
    try {
      const [nextConfig, nextSettings] = await Promise.all([api.getSystemConfig(), api.getSystemSettings()])
      setConfig(nextConfig)
      setDraft(nextSettings)
    } catch (error) {
      pushToast(error instanceof Error ? error.message : '全局设置加载失败', 'danger')
    }
  }

  useEffect(() => {
    void load()
  }, [])

  if (!config || !draft) {
    return <div className="loading-panel">加载全局设置中</div>
  }

  return (
    <motion.div className="workspace-page" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <section className="section">
        <div className="section-head">
          <h2>系统档位</h2>
          <span>当前生效档位：{config.active_profile}</span>
        </div>
        <div className="profile-grid">
          {config.profiles.map((profile) => (
            <div className={`profile-row ${profile.name === config.active_profile ? 'is-active' : ''}`} key={profile.name}>
              <div>
                <strong>{profile.name}</strong>
                <p>{profile.description}</p>
              </div>
              <div className="row-actions">
                <button
                  onClick={async () => {
                    try {
                      const result = await api.activateSystemProfile(profile.name)
                      pushToast(result.message, 'success')
                      await load()
                    } catch (error) {
                      pushToast(error instanceof Error ? error.message : '切换失败', 'danger')
                    }
                  }}
                  type="button"
                >
                  激活档位
                </button>
                <button
                  onClick={async () => {
                    try {
                      const result = await api.activateModelProfile(profile.name)
                      pushToast(result.message, 'success')
                      await load()
                    } catch (error) {
                      pushToast(error instanceof Error ? error.message : '切换失败', 'danger')
                    }
                  }}
                  type="button"
                >
                  仅切换模型档位
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>运行时设置</h2>
          <span>保存后影响所有项目</span>
        </div>
        <div className="form-grid three-col">
          <label className="field">
            <span>模型档位</span>
            <select
              onChange={(event) => setDraft({ ...draft, model_profile: event.target.value })}
              value={draft.model_profile}
            >
              {draft._meta.available_model_profiles.map((profile) => (
                <option key={profile} value={profile}>
                  {profile}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>基础模型</span>
            <input
              onChange={(event) => setDraft({ ...draft, llm: { ...draft.llm, base_model: event.target.value } })}
              value={draft.llm.base_model}
            />
          </label>
          <label className="field">
            <span>最大 token</span>
            <input
              onChange={(event) =>
                setDraft({ ...draft, llm: { ...draft.llm, max_tokens: Number(event.target.value || 0) } })
              }
              type="number"
              value={draft.llm.max_tokens}
            />
          </label>
          <label className="field">
            <span>SAM 权重</span>
            <input
              onChange={(event) => setDraft({ ...draft, sam: { ...draft.sam, checkpoint: event.target.value } })}
              value={draft.sam.checkpoint}
            />
          </label>
          <label className="field">
            <span>SAM 设备</span>
            <select
              onChange={(event) =>
                setDraft({ ...draft, sam: { ...draft.sam, device: event.target.value as 'cpu' | 'cuda' } })
              }
              value={draft.sam.device}
            >
              <option value="cpu">cpu</option>
              <option value="cuda">cuda</option>
            </select>
          </label>
          <label className="field">
            <span>评估默认 split</span>
            <select
              onChange={(event) =>
                setDraft({
                  ...draft,
                  evaluation: { ...draft.evaluation, split: event.target.value as 'train' | 'val' | 'test' },
                })
              }
              value={draft.evaluation.split}
            >
              <option value="train">train</option>
              <option value="val">val</option>
              <option value="test">test</option>
            </select>
          </label>
        </div>
        <div className="toggle-row">
          <button
            className={draft.postprocess.enable_close ? 'toggle is-on' : 'toggle'}
            onClick={() =>
              setDraft({ ...draft, postprocess: { ...draft.postprocess, enable_close: !draft.postprocess.enable_close } })
            }
            type="button"
          >
            闭运算 {draft.postprocess.enable_close ? '开启' : '关闭'}
          </button>
          <button
            className={draft.quality.enable ? 'toggle is-on' : 'toggle'}
            onClick={() => setDraft({ ...draft, quality: { ...draft.quality, enable: !draft.quality.enable } })}
            type="button"
          >
            质量评估 {draft.quality.enable ? '开启' : '关闭'}
          </button>
          <button
            className={draft.quality.enable_consistency_check ? 'toggle is-on' : 'toggle'}
            onClick={() =>
              setDraft({
                ...draft,
                quality: {
                  ...draft.quality,
                  enable_consistency_check: !draft.quality.enable_consistency_check,
                },
              })
            }
            type="button"
          >
            一致性校验 {draft.quality.enable_consistency_check ? '开启' : '关闭'}
          </button>
        </div>
        <div className="toolbar">
          <button
            className="primary-btn"
            onClick={async () => {
              try {
                const result = await api.patchSystemSettings({
                  model_profile: draft.model_profile,
                  llm: draft.llm,
                  sam: draft.sam,
                  postprocess: draft.postprocess,
                  quality: draft.quality,
                  evaluation: draft.evaluation,
                })
                pushToast(result.change.message, 'success')
                await load()
              } catch (error) {
                pushToast(error instanceof Error ? error.message : '保存失败', 'danger')
              }
            }}
            type="button"
          >
            保存全局设置
          </button>
        </div>
      </section>

      <section className="section">
        <div className="kv-grid">
          <div>
            <span>后端环境文件</span>
            <strong>{config.env_files.backend}</strong>
          </div>
          <div>
            <span>前端环境文件</span>
            <strong>{config.env_files.frontend}</strong>
          </div>
          <div>
            <span>实际后端</span>
            <strong>{config.runtime.annotation_backend}</strong>
          </div>
          <div>
            <span>vLLM 地址</span>
            <strong>{config.runtime.vllm_base_url}</strong>
          </div>
          <div>
            <span>微调后端</span>
            <strong>
              {config.runtime.finetune.effective_backend}
              {config.runtime.finetune.requested_backend !== config.runtime.finetune.effective_backend
                ? `（请求：${config.runtime.finetune.requested_backend}）`
                : ''}
            </strong>
          </div>
          <div>
            <span>LLaMA-Factory</span>
            <strong>{config.runtime.finetune.llamafactory_cli_available ? '已就绪' : '未就绪'}</strong>
          </div>
          <div>
            <span>微调说明</span>
            <strong>{config.runtime.finetune.note}</strong>
          </div>
        </div>
      </section>
    </motion.div>
  )
}
