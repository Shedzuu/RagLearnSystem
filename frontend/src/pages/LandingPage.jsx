import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import FileUpload from '../components/FileUpload'
import BlockRow from '../components/BlockRow'
import ReviewsSlider from '../components/ReviewsSlider'
import AIChatPanel from '../components/AIChatPanel'
import { useAuth } from '../context/AuthContext'
import ThemeToggle from '../components/ThemeToggle'
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
  const { user, logout } = useAuth()
  const [chatOpen, setChatOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const profileRef = useRef(null)

  useEffect(() => {
    function handleClickOutside(e) {
      if (profileRef.current && !profileRef.current.contains(e.target)) setProfileOpen(false)
    }
    if (profileOpen) document.addEventListener('click', handleClickOutside)
    return () => document.removeEventListener('click', handleClickOutside)
  }, [profileOpen])

  const handleFileSelect = (file) => {
    console.log('File selected (backend later):', file?.name)
  }

  const scrollTo = (id) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.logo}>Smart Knowledge Hub</h1>
        <nav className={styles.nav}>
          <button type="button" onClick={() => scrollTo('upload')}>
            Upload
          </button>
          <button type="button" onClick={() => scrollTo('preview')}>
            Preview
          </button>
          <button type="button" onClick={() => scrollTo('reviews')}>
            Reviews
          </button>
          <button type="button" onClick={() => scrollTo('contacts')}>
            Contacts
          </button>
        </nav>
        <div className={styles.headerRight}>
          <ThemeToggle />
          <div className={styles.profileWrap} ref={profileRef}>
          <button
            type="button"
            className={styles.profileBtn}
            onClick={() => (user ? setProfileOpen((o) => !o) : navigate('/login'))}
            aria-label="Profile"
          >
            <img src={user ? "/assets/profile_logo_after_login.png" : "/assets/user_profile.png"} alt="" className={styles.userIcon} />
          </button>
          {user && profileOpen && (
            <div className={styles.profileDropdown}>
              <p className={styles.profileName}>{user.firstName} {user.lastName}</p>
              <p role="button" tabIndex={0} className={styles.logoutText} onClick={() => { logout(); setProfileOpen(false); }} onKeyDown={(e) => e.key === 'Enter' && (logout(), setProfileOpen(false))}>
                Log out
              </p>
            </div>
          )}
          </div>
        </div>
      </header>

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
    </div>
  )
}
