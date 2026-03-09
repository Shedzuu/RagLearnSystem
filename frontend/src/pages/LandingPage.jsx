import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import FileUpload from '../components/FileUpload'
import BlockRow from '../components/BlockRow'
import ReviewsSlider from '../components/ReviewsSlider'
import AIChatPanel from '../components/AIChatPanel'
import { useAuth } from '../context/AuthContext'
import { documentsApi } from '../api/client'
import AppHeader from '../components/AppHeader'
import UploadingOverlay from '../components/UploadingOverlay'
import styles from './LandingPage.module.css'

const stepsBlocks = [
  { title: 'Upload a file', text: 'Select a file with learning material.' },
  { title: 'Name your curriculum', text: 'Specify a name for easy navigation.' },
  { title: 'Start learning', text: 'Complete tests and open-ended questions.' },
]

const reviewsBlocks = [
  { title: 'Kuanysh', text: 'Very convenient for exam preparation.' },
  { title: 'Aman', text: 'Clear interface, tests help a lot.' },
  { title: 'Temirlan', text: 'Uploaded my notes — got questions right away.' },
  { title: 'Nurzhas', text: 'Great tool for studying.' },
]

export default function LandingPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [chatOpen, setChatOpen] = useState(false)
  const [uploading, setUploading] = useState(false)

  const handleFileSelect = async (file) => {
    if (!user) {
      navigate('/login', { state: { fromUpload: true } })
      return
    }
    setUploading(true)
    try {
      await documentsApi.uploadDocument(file)
      // можно оставить короткую анимацию
      setTimeout(() => {
        setUploading(false)
        navigate('/materials')
      }, 1500)
    } catch (_) {
      setUploading(false)
      // на будущее можно показать ошибку пользователю
    }
  }

  const scrollTo = (id) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <div className={styles.page}>
      <AppHeader />

      <main className={styles.main}>
        <section className={styles.hero} id="upload">
          <h2 className={styles.heroTitle}>Start your learning</h2>
          <div className={styles.uploadWrap}>
            <FileUpload onFileSelect={handleFileSelect} />
          </div>
        </section>

        <section className={styles.section} id="preview">
          <p className={styles.sectionLabel}>preview</p>
          <BlockRow items={stepsBlocks} variant="gray" />
        </section>

        <section className={styles.section} id="reviews">
          <h2 className={styles.sectionTitle}>User reviews from the platform</h2>
          <ReviewsSlider items={reviewsBlocks} />
        </section>
      </main>

      <footer className={styles.footer} id="contacts">
        <div className={styles.footerLeft}>
          <p>Almaty region, Karasay district 040900, Kaskelen city, Abylai Khan street 1/1</p>
          <p>
            <img src="/assets/mail.png" alt="" className={styles.footerIconImg} /> info@skh.com
          </p>
          <p>
            <img src="/assets/call.png" alt="" className={styles.footerIconImg} /> +7 777 777 77 77
          </p>
        </div>
        <div className={styles.footerRight}>
          <a href="#" className={styles.social} aria-label="Facebook">
            <img src="/assets/facebook.png" alt="Facebook" />
          </a>
          <a href="#" className={styles.social} aria-label="Instagram">
            <img src="/assets/instagram.png" alt="Instagram" />
          </a>
          <a href="#" className={styles.social} aria-label="Threads">
            <img src="/assets/threads.png" alt="Threads" />
          </a>
          <a href="#" className={styles.social} aria-label="X">
            <img src="/assets/x.png" alt="X" />
          </a>
        </div>
      </footer>

      <button
        type="button"
        className={styles.chatBtn}
        onClick={() => setChatOpen(true)}
        aria-label="Open AI chat"
      >
        <img src="/assets/logo_ai_chat.png" alt="" className={styles.chatBtnIcon} />
      </button>

      <AIChatPanel isOpen={chatOpen} onClose={() => setChatOpen(false)} />
      {uploading && <UploadingOverlay />}
    </div>
  )
}
