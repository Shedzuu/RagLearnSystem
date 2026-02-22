import { useState } from 'react'
import styles from './AIChatPanel.module.css'

const FAQ_QUESTIONS = [
  'How to upload a file?',
  'How to create a curriculum?',
  'How to take tests?',
  'How to get help?',
  'What file formats are supported?',
  'How does the AI assistant work?',
]

export default function AIChatPanel({ isOpen, onClose }) {
  const [message, setMessage] = useState('')

  if (!isOpen) return null

  const handleSend = () => {
    if (!message.trim()) return
    console.log('Отправка (бекенд позже):', message)
    setMessage('')
  }

  const handleFaqClick = (q) => {
    setMessage(q)
  }

  return (
    <>
      <div className={styles.backdrop} onClick={onClose} aria-hidden="true" />
      <aside className={styles.panel} role="dialog" aria-label="Чат с ИИ">
        <header className={styles.header}>
          <h2 className={styles.title}>Al&apos;s name</h2>
          <button type="button" className={styles.close} onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </header>

        <div className={styles.body}>
          <div className={styles.iconPlaceholder}>иконка ИИ если есть</div>
          <div className={styles.faq}>
            {FAQ_QUESTIONS.map((q, i) => (
              <button key={i} type="button" className={styles.faqBtn} onClick={() => handleFaqClick(q)}>
                {q}
              </button>
            ))}
          </div>
        </div>

        <div className={styles.inputWrap}>
          <input
            type="text"
            className={styles.input}
            placeholder="Write your question here"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          />
          <button type="button" className={styles.send} onClick={handleSend} aria-label="Send">
            <img src="/assets/ai_send_arrow.png" alt="" className={styles.sendIcon} />
          </button>
        </div>
      </aside>
    </>
  )
}
