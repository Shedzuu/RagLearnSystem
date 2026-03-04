import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import AppHeader from '../components/AppHeader'
import { useAuth } from '../context/AuthContext'
import { plansApi } from '../api/client'
import styles from './UnitPage.module.css'

export default function UnitPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user, loading } = useAuth()
  const [unit, setUnit] = useState(null)
  const [attemptId, setAttemptId] = useState(null)
  const [answersState, setAnswersState] = useState({})
  const [error, setError] = useState('')
  const [loadingUnit, setLoadingUnit] = useState(true)

  useEffect(() => {
    if (!loading && !user) navigate('/login')
  }, [user, loading, navigate])

  useEffect(() => {
    if (!user) return
    let cancelled = false
    async function load() {
      setLoadingUnit(true)
      setError('')
      try {
        const data = await plansApi.getUnit(id)
        if (cancelled) return
        setUnit(data)
        // Start attempt for this plan if needed
        const attempt = await plansApi.startAttempt(data.plan_id)
        if (!cancelled) setAttemptId(attempt.attempt_id)
      } catch (e) {
        if (!cancelled) setError('Failed to load unit')
      } finally {
        if (!cancelled) setLoadingUnit(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [id, user])

  const updateAnswerState = (questionId, update) => {
    setAnswersState((prev) => ({
      ...prev,
      [questionId]: { ...(prev[questionId] || {}), ...update },
    }))
  }

  const toggleChoice = (question, choiceId) => {
    const qState = answersState[question.id] || {}
    const current = qState.selectedChoices || []
    if (question.type === 'single_choice') {
      updateAnswerState(question.id, { selectedChoices: [choiceId] })
    } else if (question.type === 'multiple_choice') {
      const exists = current.includes(choiceId)
      const next = exists ? current.filter((id2) => id2 !== choiceId) : [...current, choiceId]
      updateAnswerState(question.id, { selectedChoices: next })
    }
  }

  const submitAnswer = async (question) => {
    if (!attemptId) return
    const qState = answersState[question.id] || {}
    const payload = {
      attempt_id: attemptId,
      question_id: question.id,
      text_answer: qState.textAnswer || '',
      code_answer: qState.codeAnswer || '',
      selected_choices: (qState.selectedChoices || []).map((choiceId) => ({ choice_id: choiceId })),
    }
    try {
      const result = await plansApi.submitAnswer(payload)
      updateAnswerState(question.id, {
        lastResult: {
          is_correct: result.is_correct,
          earned_points: result.earned_points,
        },
      })
    } catch (e) {
      updateAnswerState(question.id, {
        lastResult: { error: 'Failed to submit answer' },
      })
    }
  }

  if (loading || !user) return null

  return (
    <div className={styles.page}>
      <AppHeader />
      <main className={styles.main}>
        {loadingUnit ? (
          <p className={styles.muted}>Loading unit...</p>
        ) : error ? (
          <p className={styles.error}>{error}</p>
        ) : !unit ? (
          <p className={styles.error}>Unit not found.</p>
        ) : (
          <div className={styles.content}>
            <h1 className={styles.title}>{unit.title}</h1>
            <section className={styles.theory}>
              <h2 className={styles.sectionTitle}>Theory</h2>
              <p className={styles.theoryText}>{unit.theory}</p>
            </section>
            {unit.questions.length > 0 && (
              <section className={styles.questions}>
                <h2 className={styles.sectionTitle}>Questions</h2>
                <ul className={styles.questionList}>
                  {unit.questions.map((q) => {
                    const qState = answersState[q.id] || {}
                    return (
                      <li key={q.id} className={styles.questionItem}>
                        <p className={styles.questionText}>{q.text}</p>
                        {q.type === 'single_choice' || q.type === 'multiple_choice' ? (
                          <ul className={styles.choiceList}>
                            {q.choices.map((ch) => {
                              const selected = (qState.selectedChoices || []).includes(ch.id)
                              return (
                                <li key={ch.id}>
                                  <label className={styles.choiceLabel}>
                                    <input
                                      type={q.type === 'single_choice' ? 'radio' : 'checkbox'}
                                      name={`q-${q.id}`}
                                      checked={selected}
                                      onChange={() => toggleChoice(q, ch.id)}
                                    />
                                    <span>{ch.text}</span>
                                  </label>
                                </li>
                              )
                            })}
                          </ul>
                        ) : (
                          <textarea
                            className={styles.textarea}
                            rows={3}
                            placeholder={q.type === 'code' ? 'Write your code here...' : 'Write your answer here...'}
                            value={qState.textAnswer || ''}
                            onChange={(e) =>
                              updateAnswerState(q.id, { textAnswer: e.target.value })
                            }
                          />
                        )}
                        <button
                          type="button"
                          className={styles.submitBtn}
                          onClick={() => submitAnswer(q)}
                          disabled={!attemptId}
                        >
                          Submit answer
                        </button>
                        {qState.lastResult && (
                          <p
                            className={
                              qState.lastResult.error
                                ? styles.error
                                : qState.lastResult.is_correct
                                ? styles.correct
                                : styles.incorrect
                            }
                          >
                            {qState.lastResult.error
                              ? qState.lastResult.error
                              : qState.lastResult.is_correct
                              ? 'Correct!'
                              : 'Incorrect.'}
                          </p>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </section>
            )}
          </div>
        )}
      </main>
    </div>
  )
}

