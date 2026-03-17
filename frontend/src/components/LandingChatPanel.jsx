import { useState, useRef, useEffect } from 'react'
import { plansApi } from '../api/client'
import styles from './LandingChatPanel.module.css'

const QUICK_QA = {
  'How do I upload a file?':
    'On the **main page**, you\'ll see an upload area — just drag & drop your file (PDF, DOCX, or TXT) or click to browse. You can also go to **Materials** in the top menu and upload from there. After uploading, the file appears in your Materials library.',
  'How do I create a study plan?':
    'Go to **Plans** in the top menu → click **Create Plan**. Give it a title, an optional description, and your learning goals (e.g. "Learn Python basics"). Then attach one or more documents from your Materials library and click **Generate**. The AI will build a structured course for you automatically.',
  'How does AI generate a course?':
    'When you click **Generate**, the system:\n1. Splits your documents into chunks\n2. Uses **RAG** (Retrieval-Augmented Generation) to find relevant content\n3. Asks an AI model to create **Sections → Units → Theory + Questions** based strictly on your materials\n\nThe result is a full course with theory explanations and various question types (single choice, multiple choice, open text, code).',
  'How do I take tests?':
    'Open any **Plan** → click on a **Unit** in the left sidebar. You\'ll see the theory at the top and questions below. Answer all questions, then click **Submit answers** at the bottom. You\'ll immediately see your score and which answers were correct or wrong. If you didn\'t pass, click **Retry unit** to try again.',
  'How does progress tracking work?':
    'In the left sidebar of any unit page you\'ll see two progress bars:\n- **Plan** — shows how many units you\'ve completed across the entire plan\n- **This unit** — shows how many questions you answered correctly\n\nOnly **correctly answered** questions count toward progress. A unit is marked "Done" only when all its questions are answered correctly.',
  'What is the AI Tutor?':
    'On every unit page, there\'s an **AI chat panel on the right**. You can ask it anything about the current theory. There\'s also a 💡 **lightbulb icon** next to each question — click it to get targeted help for that specific question.\n\nThe AI Tutor gives **hints and explanations**, not direct answers, to help you actually learn the material.',
}

const QUICK_QUESTIONS = Object.keys(QUICK_QA)

export default function LandingChatPanel({ isOpen, onClose }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bodyRef = useRef(null)

  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  }, [messages])

  const handleClose = () => {
    setMessages([])
    setInput('')
    onClose()
  }

  if (!isOpen) return null

  const handleQuickQuestion = (question) => {
    const answer = QUICK_QA[question]
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: question },
      { role: 'assistant', content: answer },
    ])
  }

  const sendMessage = async (text) => {
    if (!text.trim() || loading) return
    const trimmed = text.trim()

    if (QUICK_QA[trimmed]) {
      setInput('')
      handleQuickQuestion(trimmed)
      return
    }

    const userMsg = { role: 'user', content: trimmed }
    const updatedMessages = [...messages, userMsg]
    setMessages(updatedMessages)
    setInput('')
    setLoading(true)

    try {
      const res = await plansApi.sendLandingChat({
        message: trimmed,
        history: updatedMessages.map((m) => ({ role: m.role, content: m.content })),
      })
      setMessages((prev) => [...prev, { role: 'assistant', content: res.reply }])
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Sorry, something went wrong. Please try again.' },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <div className={styles.backdrop} onClick={handleClose} aria-hidden="true" />
      <aside className={styles.panel} role="dialog" aria-label="AI Chat">
        <header className={styles.header}>
          <h2 className={styles.title}>AI Assistant</h2>
          <button type="button" className={styles.closeBtn} onClick={handleClose} aria-label="Close">
            ×
          </button>
        </header>

        <div className={styles.body} ref={bodyRef}>
          {messages.length === 0 && (
            <div className={styles.welcome}>
              <img src="/assets/ai_robot.png" alt="AI" className={styles.welcomeIcon} />
              <p className={styles.welcomeText}>
                Hi! I can help you understand how Smart Knowledge Hub works. Ask me anything or pick a question below.
              </p>
              <div className={styles.quickGrid}>
                {QUICK_QUESTIONS.map((q, i) => (
                  <button
                    key={i}
                    type="button"
                    className={styles.quickBtn}
                    onClick={() => handleQuickQuestion(q)}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((msg, i) => (
            <div
              key={i}
              className={msg.role === 'user' ? styles.msgUser : styles.msgAssistant}
            >
              <div className={styles.msgContent}>{msg.content}</div>
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
            placeholder="Ask about the platform..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage(input)}
            disabled={loading}
          />
          <button
            type="button"
            className={styles.sendBtn}
            onClick={() => sendMessage(input)}
            disabled={loading || !input.trim()}
          >
            ↑
          </button>
        </div>
      </aside>
    </>
  )
}
