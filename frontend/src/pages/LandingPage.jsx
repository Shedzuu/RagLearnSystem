import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import FileUpload from '../components/FileUpload'
import BlockRow from '../components/BlockRow'
import ReviewsSlider from '../components/ReviewsSlider'
import LandingChatPanel from '../components/LandingChatPanel'
import { useAuth } from '../context/AuthContext'
import { documentsApi } from '../api/client'
import AppHeader from '../components/AppHeader'
import UploadingOverlay from '../components/UploadingOverlay'
import styles from './LandingPage.module.css'

const stepsBlocks = [
  {
    title: 'Upload a file',
    text: 'Bring in lecture notes, textbook pages or summaries and keep them in one study space.',
    image: 'https://images.unsplash.com/photo-1522202176988-66273c2fd55f?auto=format&fit=crop&w=900&q=80',
  },
  {
    title: 'Name your curriculum',
    text: 'Turn raw materials into a structured path with clear goals, sections and next steps.',
    image: 'https://images.unsplash.com/photo-1455390582262-044cdead277a?auto=format&fit=crop&w=900&q=80',
  },
  {
    title: 'Start learning',
    text: 'Move through theory, practice tasks and progress tracking without switching between tools.',
    image: 'https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=900&q=80',
  },
]

const featurePills = [
  'Fast material upload',
  'AI-assisted plan creation',
  'Practice with tests and open questions',
]

const reviewsBlocks = [
  {
    title: 'Kuanysh',
    meta: 'Economics student',
    text: 'Very convenient for exam preparation. I uploaded my materials and got a clean structure almost immediately.',
    image: 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=700&q=80',
  },
  {
    title: 'Aman',
    meta: 'University applicant',
    text: 'The interface feels clear, and the tests really help me understand what I remember well.',
    image: 'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?auto=format&fit=crop&w=700&q=80',
  },
  {
    title: 'Temirlan',
    meta: 'Engineering student',
    text: 'Uploaded my notes and started practicing right away. It saves a lot of time before exams.',
    image: 'https://images.unsplash.com/photo-1504593811423-6dd665756598?auto=format&fit=crop&w=700&q=80',
  },
  {
    title: 'Nurzhas',
    meta: 'Self-learner',
    text: 'A strong tool for studying. The step-by-step flow helps me stay focused instead of getting lost in files.',
    image: 'https://images.unsplash.com/photo-1507591064344-4c6ce005b128?auto=format&fit=crop&w=700&q=80',
  },
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
      setTimeout(() => {
        setUploading(false)
        navigate('/materials')
      }, 1500)
    } catch (_) {
      setUploading(false)
    }
  }

  return (
    <div className={styles.page}>
      <AppHeader />

      <main className={styles.main}>
        <section className={styles.hero} id="upload">
          <div className={styles.heroText}>
            <p className={styles.eyebrow}>Smart study workspace</p>
            <h2 className={styles.heroTitle}>Start your learning</h2>
            <p className={styles.heroSubtitle}>
              Upload your notes or materials, turn them into a study plan, and move
              through theory, questions, and progress tracking in one place.
            </p>
          </div>
          <div className={styles.heroCard}>
            <div className={styles.uploadWrap}>
              <FileUpload onFileSelect={handleFileSelect} />
            </div>
            <div className={styles.featureRow}>
              {featurePills.map((item) => (
                <span key={item} className={styles.featurePill}>{item}</span>
              ))}
            </div>
          </div>
        </section>

        <section className={styles.section} id="preview">
          <p className={styles.sectionLabel}>How it works</p>
          <h3 className={styles.sectionTitle}>A simple flow from material to practice</h3>
          <p className={styles.sectionSubtitle}>
            Upload once, shape the learning path, and continue with theory, questions and progress in one calm workspace.
          </p>
          <BlockRow items={stepsBlocks} variant="gray" />
        </section>

        <section className={styles.section} id="reviews">
          <p className={styles.sectionLabel}>Reviews</p>
          <h2 className={styles.sectionTitle}>What learners like about the platform</h2>
          <p className={styles.sectionSubtitle}>
            Students use it to organize materials faster and stay more consistent during preparation.
          </p>
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

      <LandingChatPanel isOpen={chatOpen} onClose={() => setChatOpen(false)} />
      {uploading && <UploadingOverlay />}
    </div>
  )
}
