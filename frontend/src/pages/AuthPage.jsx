import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import ThemeToggle from '../components/ThemeToggle'
import styles from './AuthPage.module.css'

export default function AuthPage() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [mode, setMode] = useState('signin')
  const [signIn, setSignIn] = useState({ email: '', password: '' })
  const [signUp, setSignUp] = useState({
    firstName: '',
    lastName: '',
    email: '',
    password: '',
    confirmPassword: '',
  })

  const switchToSignUp = () => setMode('signup')
  const switchToSignIn = () => setMode('signin')

  const handleSignInSubmit = (e) => {
    e.preventDefault()
    login({ firstName: 'User', lastName: 'Demo' })
    navigate('/')
  }

  const handleSignUpSubmit = (e) => {
    e.preventDefault()
    login({ firstName: signUp.firstName, lastName: signUp.lastName })
    navigate('/')
  }

  const handleGoogle = () => {
    login({ firstName: 'Google', lastName: 'User' })
    navigate('/')
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Link to="/" className={styles.logo}>Smart Knowledge Hub</Link>
        <ThemeToggle />
      </header>
      <div className={styles.cardWrap}>
      <div className={styles.card}>
        <h1 className={styles.title}>Welcome</h1>

        <div className={`${styles.formWrap} ${mode === 'signin' ? styles.formWrapSignIn : styles.formWrapSignUp}`}>
          <div className={styles.form}>
            <form onSubmit={handleSignInSubmit}>
              <p className={styles.subtitle}>Sign in to your account</p>
              <label className={styles.label}>
                Email address
                <input
                  type="email"
                  className={styles.input}
                  value={signIn.email}
                  onChange={(e) => setSignIn((s) => ({ ...s, email: e.target.value }))}
                  required
                />
              </label>
              <label className={styles.label}>
                Password
                <input
                  type="password"
                  className={styles.input}
                  value={signIn.password}
                  onChange={(e) => setSignIn((s) => ({ ...s, password: e.target.value }))}
                  required
                />
              </label>
              <a href="#" className={styles.link}>Forgot password?</a>
              <button type="submit" className={styles.btn}>Log in</button>
              <p className={styles.switch}>
                No account?{' '}
                <button type="button" className={styles.linkBtn} onClick={switchToSignUp}>
                  Register
                </button>
              </p>
            </form>
          </div>
          <div className={styles.form}>
            <form onSubmit={handleSignUpSubmit}>
              <p className={styles.subtitle}>Start your learning with us</p>
              <label className={styles.label}>
                Name
                <input
                  type="text"
                  className={styles.input}
                  value={signUp.firstName}
                  onChange={(e) => setSignUp((s) => ({ ...s, firstName: e.target.value }))}
                  required
                />
              </label>
              <label className={styles.label}>
                Surname
                <input
                  type="text"
                  className={styles.input}
                  value={signUp.lastName}
                  onChange={(e) => setSignUp((s) => ({ ...s, lastName: e.target.value }))}
                  required
                />
              </label>
              <label className={styles.label}>
                Email address
                <input
                  type="email"
                  className={styles.input}
                  value={signUp.email}
                  onChange={(e) => setSignUp((s) => ({ ...s, email: e.target.value }))}
                  required
                />
              </label>
              <label className={styles.label}>
                Password
                <input
                  type="password"
                  className={styles.input}
                  value={signUp.password}
                  onChange={(e) => setSignUp((s) => ({ ...s, password: e.target.value }))}
                  required
                />
              </label>
              <label className={styles.label}>
                Confirm password
                <input
                  type="password"
                  className={styles.input}
                  value={signUp.confirmPassword}
                  onChange={(e) => setSignUp((s) => ({ ...s, confirmPassword: e.target.value }))}
                  required
                />
              </label>
              <button type="submit" className={styles.btn}>Register</button>
              <p className={styles.switch}>
                Have an account?{' '}
                <button type="button" className={styles.linkBtn} onClick={switchToSignIn}>
                  Log in
                </button>
              </p>
            </form>
          </div>
        </div>

        <div className={styles.social}>
          <p className={styles.socialLabel}>Or continue with</p>
          <button type="button" className={styles.googleBtn} onClick={handleGoogle}>
            <img src="/assets/google_logo.png" alt="Google" className={styles.googleIcon} />
          </button>
        </div>
      </div>
      </div>
    </div>
  )
}
