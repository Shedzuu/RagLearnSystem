import { useState, useRef, useEffect } from 'react'
import { Link, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import ThemeToggle from './ThemeToggle'
import styles from './AppHeader.module.css'

export default function AppHeader() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuth()
  const [profileOpen, setProfileOpen] = useState(false)
  const profileRef = useRef(null)

  useEffect(() => {
    function handleClickOutside(e) {
      if (profileRef.current && !profileRef.current.contains(e.target)) setProfileOpen(false)
    }
    if (profileOpen) document.addEventListener('click', handleClickOutside)
    return () => document.removeEventListener('click', handleClickOutside)
  }, [profileOpen])

  const scrollTo = (id) => {
    if (window.location.pathname !== '/') {
      navigate(`/#${id}`)
      return
    }
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  }

  const onLanding = location.pathname === '/'
  const displayName = user
    ? [user.firstName, user.lastName].filter(Boolean).join(' ') || user.email
    : ''

  return (
    <header className={styles.header}>
      <Link to="/" className={styles.logo}>Smart Knowledge Hub</Link>
      <nav className={styles.nav}>
        {onLanding ? (
          <>
            <button type="button" className={styles.navBtn} onClick={() => scrollTo('upload')}>Upload</button>
            <button type="button" className={styles.navBtn} onClick={() => scrollTo('preview')}>Preview</button>
            <button type="button" className={styles.navBtn} onClick={() => scrollTo('reviews')}>Reviews</button>
            <button type="button" className={styles.navBtn} onClick={() => scrollTo('contacts')}>Contacts</button>
          </>
        ) : (
          <>
            {user && (
              <>
                <NavLink to="/plans" className={({ isActive }) => `${styles.navLink} ${isActive ? styles.navLinkActive : ''}`}>
                  Plans
                </NavLink>
                <NavLink to="/materials" className={({ isActive }) => `${styles.navLink} ${isActive ? styles.navLinkActive : ''}`}>
                  Materials
                </NavLink>
                <NavLink to="/account" className={({ isActive }) => `${styles.navLink} ${isActive ? styles.navLinkActive : ''}`}>
                  Account
                </NavLink>
              </>
            )}
          </>
        )}
      </nav>
      <div className={styles.headerRight}>
        <ThemeToggle />
        {user && (
          <button type="button" className={styles.accountChip} onClick={() => navigate('/account')}>
            <span className={styles.accountChipName}>{displayName}</span>
            <span className={styles.accountChipPlan}>{user.subscriptionPlanLabel}</span>
          </button>
        )}
        <div className={styles.profileWrap} ref={profileRef}>
          <button
            type="button"
            className={styles.profileBtn}
            onClick={() => (user ? setProfileOpen((o) => !o) : navigate('/login'))}
            aria-label="Profile"
          >
            <img src={user ? '/assets/profile_logo_after_login.png' : '/assets/user_profile.png'} alt="" className={styles.userIcon} />
          </button>
          {user && profileOpen && (
            <div className={styles.profileDropdown}>
              <p className={styles.profileName}>{displayName}</p>
              <p className={styles.profilePlan}>{user.subscriptionPlanLabel} plan</p>
              <button
                type="button"
                className={styles.profileMenuBtn}
                onClick={() => {
                  navigate('/account')
                  setProfileOpen(false)
                }}
              >
                Account
              </button>
              <button
                type="button"
                className={styles.profileMenuBtn}
                onClick={() => {
                  navigate('/plans')
                  setProfileOpen(false)
                }}
              >
                Plans
              </button>
              <p role="button" tabIndex={0} className={styles.logoutText} onClick={() => { logout(); setProfileOpen(false); }} onKeyDown={(e) => e.key === 'Enter' && (logout(), setProfileOpen(false))}>
                Log out
              </p>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
