import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import AppHeader from '../components/AppHeader'
import { useAuth } from '../context/AuthContext'
import styles from './AccountPage.module.css'

const planCards = [
  {
    id: 'free',
    title: 'Free',
    price: '$0',
    description: 'For trying the platform and keeping access to your account.',
    features: ['Basic account access', 'View your existing plans', 'Manual upgrade anytime'],
  },
  {
    id: 'monthly',
    title: 'Monthly',
    price: '$9.99 / month',
    description: 'Flexible subscription for regular learning.',
    features: ['Active study subscription', 'Auto renew support', 'Monthly billing cycle'],
  },
  {
    id: 'yearly',
    title: 'Yearly',
    price: '$79.99 / year',
    description: 'Best value for long-term use.',
    features: ['Full-year access', 'Lower effective monthly cost', 'Auto renew support'],
  },
]

const planPriceMap = {
  free: '$0',
  monthly: '$9.99',
  yearly: '$79.99',
}

function formatDate(value) {
  if (!value) return 'Not set'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Not set'
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(date)
}

function formatCardNumber(value) {
  return value
    .replace(/\D/g, '')
    .slice(0, 19)
    .replace(/(.{4})/g, '$1 ')
    .trim()
}

export default function AccountPage() {
  const navigate = useNavigate()
  const { user, loading, updateSubscription } = useAuth()
  const [selectedPlan, setSelectedPlan] = useState(user?.subscriptionPlan || 'free')
  const [autoRenew, setAutoRenew] = useState(user?.subscriptionAutoRenew ?? true)
  const [paymentForm, setPaymentForm] = useState({
    cardholderName: '',
    cardNumber: '',
    expiryMonth: '',
    expiryYear: '',
    cvv: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    if (user) {
      setSelectedPlan(user.subscriptionPlan)
      setAutoRenew(user.subscriptionAutoRenew)
    }
  }, [user])

  useEffect(() => {
    if (!loading && !user) navigate('/login')
  }, [loading, user, navigate])

  if (loading || !user) return null

  const requiresPayment = selectedPlan !== 'free' && selectedPlan !== user.subscriptionPlan

  const validatePaymentForm = () => {
    const errors = []
    if (!paymentForm.cardholderName.trim()) errors.push('Cardholder name is required.')
    if (paymentForm.cardNumber.replace(/\s/g, '').length < 13) errors.push('Card number looks incomplete.')
    if (!paymentForm.expiryMonth || !paymentForm.expiryYear) errors.push('Expiry date is required.')
    if (paymentForm.cvv.length < 3) errors.push('Security code looks incomplete.')
    return errors
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError('')
    setSuccess('')
    const paymentErrors = requiresPayment ? validatePaymentForm() : []
    if (paymentErrors.length > 0) {
      setError(paymentErrors[0])
      setSubmitting(false)
      return
    }
    try {
      const updated = await updateSubscription({
        plan: selectedPlan,
        autoRenew,
        paymentMethod: requiresPayment
          ? {
              cardholder_name: paymentForm.cardholderName.trim(),
              card_number: paymentForm.cardNumber.replace(/\s/g, ''),
              expiry_month: paymentForm.expiryMonth,
              expiry_year: paymentForm.expiryYear,
              cvv: paymentForm.cvv,
            }
          : undefined,
      })
      setSelectedPlan(updated.subscriptionPlan)
      setAutoRenew(updated.subscriptionAutoRenew)
      setPaymentForm({
        cardholderName: '',
        cardNumber: '',
        expiryMonth: '',
        expiryYear: '',
        cvv: '',
      })
      setSuccess(
        updated.subscriptionPlan === 'free'
          ? 'Subscription canceled. Your account is now on the Free plan.'
          : `Subscription updated to the ${updated.subscriptionPlanLabel} plan.`
      )
    } catch (err) {
      setError(err.body?.detail || err.message || 'Failed to update subscription')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.page}>
      <AppHeader />
      <main className={styles.main}>
        <section className={styles.hero}>
          <div>
            <p className={styles.eyebrow}>Account</p>
            <h1 className={styles.title}>Manage your subscription</h1>
            <p className={styles.subtitle}>
              Choose the plan that fits your study pace and update it anytime.
            </p>
          </div>
          <div className={styles.summary}>
            <p className={styles.summaryLabel}>Current plan</p>
            <p className={styles.summaryValue}>{user.subscriptionPlanLabel}</p>
            <p className={styles.summaryMeta}>Started: {formatDate(user.subscriptionStartedAt)}</p>
            <p className={styles.summaryMeta}>Ends: {formatDate(user.subscriptionEndsAt)}</p>
            <p className={styles.summaryMeta}>
              Auto renew: {user.subscriptionAutoRenew ? 'Enabled' : 'Disabled'}
            </p>
            {user.latestPayment && (
              <div className={styles.latestPayment}>
                <p className={styles.summaryLabel}>Latest payment</p>
                <p className={styles.summaryMeta}>
                  {user.latestPayment.card_brand} ending in {user.latestPayment.card_last4}
                </p>
                <p className={styles.summaryMeta}>
                  {user.latestPayment.amount} {user.latestPayment.currency} on {formatDate(user.latestPayment.paid_at)}
                </p>
              </div>
            )}
          </div>
        </section>

        <form className={styles.form} onSubmit={handleSubmit}>
          <div className={styles.grid}>
            {planCards.map((plan) => {
              const active = selectedPlan === plan.id
              return (
                <label
                  key={plan.id}
                  className={`${styles.card} ${active ? styles.cardActive : ''}`}
                >
                  <input
                    type="radio"
                    name="subscriptionPlan"
                    value={plan.id}
                    checked={active}
                    onChange={() => setSelectedPlan(plan.id)}
                    className={styles.radio}
                  />
                  <div className={styles.cardTop}>
                    <div>
                      <h2 className={styles.cardTitle}>{plan.title}</h2>
                      <p className={styles.cardPrice}>{plan.price}</p>
                    </div>
                    {user.subscriptionPlan === plan.id && (
                      <span className={styles.currentBadge}>Current</span>
                    )}
                  </div>
                  <p className={styles.cardDescription}>{plan.description}</p>
                  <ul className={styles.featureList}>
                    {plan.features.map((feature) => (
                      <li key={feature}>{feature}</li>
                    ))}
                  </ul>
                </label>
              )
            })}
          </div>

          <label className={styles.checkboxRow}>
            <input
              type="checkbox"
              checked={autoRenew}
              onChange={(e) => setAutoRenew(e.target.checked)}
              disabled={selectedPlan === 'free'}
            />
            Renew automatically when the current paid period ends
          </label>

          {requiresPayment && (
            <section className={styles.checkout}>
              <div className={styles.checkoutHeader}>
                <div>
                  <p className={styles.checkoutLabel}>Checkout</p>
                  <h2 className={styles.checkoutTitle}>Add payment details</h2>
                </div>
                <div className={styles.checkoutAmount}>
                  <span>Charge today</span>
                  <strong>{planPriceMap[selectedPlan]}</strong>
                </div>
              </div>
              <div className={styles.checkoutGrid}>
                <label className={styles.field}>
                  Cardholder name
                  <input
                    type="text"
                    value={paymentForm.cardholderName}
                    onChange={(e) =>
                      setPaymentForm((current) => ({ ...current, cardholderName: e.target.value }))
                    }
                    placeholder="Jane Doe"
                  />
                </label>
                <label className={`${styles.field} ${styles.fieldWide}`}>
                  Card number
                  <input
                    type="text"
                    inputMode="numeric"
                    value={paymentForm.cardNumber}
                    onChange={(e) =>
                      setPaymentForm((current) => ({
                        ...current,
                        cardNumber: formatCardNumber(e.target.value),
                      }))
                    }
                    placeholder="4242 4242 4242 4242"
                  />
                </label>
                <label className={styles.field}>
                  Expiry month
                  <input
                    type="text"
                    inputMode="numeric"
                    value={paymentForm.expiryMonth}
                    onChange={(e) =>
                      setPaymentForm((current) => ({
                        ...current,
                        expiryMonth: e.target.value.replace(/\D/g, '').slice(0, 2),
                      }))
                    }
                    placeholder="08"
                  />
                </label>
                <label className={styles.field}>
                  Expiry year
                  <input
                    type="text"
                    inputMode="numeric"
                    value={paymentForm.expiryYear}
                    onChange={(e) =>
                      setPaymentForm((current) => ({
                        ...current,
                        expiryYear: e.target.value.replace(/\D/g, '').slice(0, 4),
                      }))
                    }
                    placeholder="2027"
                  />
                </label>
                <label className={styles.field}>
                  CVV
                  <input
                    type="password"
                    inputMode="numeric"
                    value={paymentForm.cvv}
                    onChange={(e) =>
                      setPaymentForm((current) => ({
                        ...current,
                        cvv: e.target.value.replace(/\D/g, '').slice(0, 4),
                      }))
                    }
                    placeholder="123"
                  />
                </label>
              </div>
            </section>
          )}

          {error && <p className={styles.error}>{error}</p>}
          {success && <p className={styles.success}>{success}</p>}

          <div className={styles.actions}>
            <button type="button" className={styles.secondaryBtn} onClick={() => navigate('/plans')}>
              Back to plans
            </button>
            <button type="submit" className={styles.primaryBtn} disabled={submitting}>
              {submitting ? 'Saving...' : 'Save subscription'}
            </button>
          </div>
        </form>
      </main>
    </div>
  )
}
