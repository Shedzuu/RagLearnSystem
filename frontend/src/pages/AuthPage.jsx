import { useState } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import ThemeToggle from '../components/ThemeToggle'
import styles from './AuthPage.module.css'

export default function AuthPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { login, register } = useAuth()
  const [mode, setMode] = useState('signin')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [signIn, setSignIn] = useState({ email: '', password: '' })
  const [signUp, setSignUp] = useState({
    firstName: '',
    lastName: '',
    email: '',
    password: '',
    confirmPassword: '',
  })

  const switchToSignUp = () => { setMode('signup'); setError('') }
  const switchToSignIn = () => { setMode('signin'); setError('') }

  const redirectAfterLogin = () => {
    if (location.state?.fromUpload) navigate('/create-plan')
    else navigate('/')
  }

  const handleSignInSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(signIn.email, signIn.password)
      redirectAfterLogin()
    } catch (err) {
      setError(err.body?.detail || err.message || 'Login failed')
    } finally {
      setSubmitting(false)
    }
  }

  const handleSignUpSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (signUp.password !== signUp.confirmPassword) {
      setError('Passwords do not match')
      return
    }
    setSubmitting(true)
    try {
      await register({
        email: signUp.email,
        password: signUp.password,
        password_confirm: signUp.confirmPassword,
        first_name: signUp.firstName,
        last_name: signUp.lastName,
      })
      redirectAfterLogin()
    } catch (err) {
      const msg = err.body?.email?.[0] || err.body?.password?.[0] || err.body?.password_confirm?.[0] || err.message || 'Registration failed'
      setError(typeof msg === 'string' ? msg : msg.join?.(' ') || 'Registration failed')
    } finally {
      setSubmitting(false)
    }
  }

  const handleGoogle = () => {
    setError('Google login is not connected to the backend yet')
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
        {error && <p className={styles.error}>{error}</p>}
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
              <button type="submit" className={styles.btn} disabled={submitting}>
                {submitting ? 'Logging in…' : 'Log in'}
              </button>
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
              <button type="submit" className={styles.btn} disabled={submitting}>
                {submitting ? 'Registering…' : 'Register'}
              </button>
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
