import { useEffect, useRef, useState } from 'react'
import { plansApi } from '../api/client'
import { stripLightMarkdown } from '../utils/plainChatText'
import styles from './PreplanChatPanel.module.css'

export default function PreplanChatPanel({ isOpen, onClose, documentIds, onApplyGoals }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [suggestedGoals, setSuggestedGoals] = useState('')
  const bodyRef = useRef(null)

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight
  }, [messages])

  const handleClose = () => {
    setMessages([])
    setInput('')
    setSuggestedGoals('')
    onClose()
  }

  if (!isOpen) return null

  const resolveMode = (text, requestedMode = 'auto') => {
    if (requestedMode === 'semantic' || requestedMode === 'exact') return requestedMode
    return 'auto'
  }

  const sendMessage = async (text, mode = 'auto') => {
    const trimmed = (text || '').trim()
    if (!trimmed || loading) return
    const resolvedMode = resolveMode(trimmed, mode)

    const userMsg = { role: 'user', content: trimmed }
    const updated = [...messages, userMsg]
    setMessages(updated)
    setInput('')
    setLoading(true)

    try {
      const serializedHistory = updated.map((m) => {
        if (m.kind === 'exact_topics') {
          const lines = (m.exactTopics || []).map((t) => {
            const title = t?.title || ''
            const page = t?.page === null || t?.page === undefined ? 'unknown' : String(t.page)
            return `- ${title} (page: ${page})`
          })
          return {
            role: m.role,
            content: `Exact topics from sources:\n${lines.join('\n')}`,
          }
        }
        return { role: m.role, content: m.content }
      })
      const res = await plansApi.sendPreplanChat({
        documentIds,
        message: trimmed,
        history: serializedHistory,
        mode: resolvedMode,
      })
      if (res.suggested_goals) setSuggestedGoals(res.suggested_goals)
      setMessages((prev) => {
        const next = [...prev, { role: 'assistant', content: res.reply || '' }]
        if (resolvedMode === 'exact' && Array.isArray(res.exact_topics) && res.exact_topics.length > 0) {
          next.push({
            role: 'assistant',
            content: '',
            kind: 'exact_topics',
            exactTopics: res.exact_topics,
          })
        }
        return next
      })
    } catch (e) {
      const msg =
        e?.body?.detail ||
        'AI is not available right now. Please configure LLM_API_KEY on the backend and try again.'
      setMessages((prev) => [...prev, { role: 'assistant', content: msg }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <div className={styles.backdrop} onClick={handleClose} aria-hidden="true" />
      <aside className={styles.panel} role="dialog" aria-label="Pre-plan AI chat">
        <header className={styles.header}>
          <h2 className={styles.title}>AI: refine goals</h2>
          <button type="button" className={styles.closeBtn} onClick={handleClose} aria-label="Close">
            ×
          </button>
        </header>

        <div className={styles.meta}>
          <div className={styles.metaRow}>
            <img src="/assets/ai_robot.png" alt="AI" className={styles.metaIcon} />
            <div className={styles.metaText}>
              Selected documents: <strong>{documentIds?.length || 0}</strong>
            </div>
          </div>
          <div className={styles.quickRow}>
            <button
              type="button"
              className={styles.quickBtn}
              onClick={() =>
                sendMessage(
                  'List the main topics you found in the selected materials. Ask me 3-5 clarifying questions, then propose a suggested goals text for the plan.'
                )
              }
              disabled={loading}
            >
              Analyze materials
            </button>
            <button
              type="button"
              className={styles.quickBtn}
              onClick={() =>
                sendMessage(
                  'Extract exact topic names from the selected materials. Do not paraphrase.',
                  'exact'
                )
              }
              disabled={loading}
            >
              Extract exact topics
            </button>
            {suggestedGoals && (
              <button
                type="button"
                className={styles.applyBtn}
                onClick={() => onApplyGoals(suggestedGoals)}
              >
                Use suggested goals
              </button>
            )}
          </div>
        </div>

        <div className={styles.body} ref={bodyRef}>
          {messages.length === 0 && (
            <div className={styles.welcome}>
              <p className={styles.welcomeText}>
                I can read the selected documents and help you write better learning goals for a higher-quality plan.
              </p>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={msg.role === 'user' ? styles.msgUser : styles.msgAssistant}>
              <div className={styles.msgContent}>
                {msg.kind === 'exact_topics' ? (
                  <section className={styles.exactTopicsBox}>
                    <div className={styles.exactTopicsHeader}>
                      <strong>Exact topics from sources</strong>
                      <button
                        type="button"
                        className={styles.applyBtn}
                        onClick={() =>
                          onApplyGoals(
                            (msg.exactTopics || [])
                              .map((item) => `- ${item?.title || ''}`.trim())
                              .filter((line) => line !== '-')
                              .join('\n')
                          )
                        }
                      >
                        Use exact topics in goals
                      </button>
                    </div>
                    <ul className={styles.exactTopicsList}>
                      {(msg.exactTopics || []).map((item, idx) => (
                        <li key={`${item?.title || 'topic'}-${idx}`} className={styles.exactTopicItem}>
                          <div className={styles.exactTopicTitle}>{item?.title || 'Untitled topic'}</div>
                          <div className={styles.exactTopicMeta}>
                            {item?.page === null || item?.page === undefined ? 'page: unknown' : `page: ${item.page}`}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : (
                  stripLightMarkdown(msg.content)
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className={styles.msgAssistant}>
              <div className={styles.msgContent}>
                <span className={styles.typing}>Thinking…</span>
              </div>
            </div>
          )}
        </div>

        <div className={styles.inputWrap}>
          <input
            type="text"
            className={styles.input}
            placeholder="Ask AI about topics/goals..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage(input, 'auto')}
            disabled={loading}
          />
          <button
            type="button"
            className={styles.sendBtn}
            onClick={() => sendMessage(input, 'auto')}
            disabled={loading || !input.trim()}
          >
            ↑
          </button>
        </div>
      </aside>
    </>
  )
}

