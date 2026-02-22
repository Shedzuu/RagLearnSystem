import styles from './UploadingOverlay.module.css'

/**
 * Оверлей загрузки: текст как на design/uploading.png + анимация прогресса.
 */
export default function UploadingOverlay() {
  return (
    <div className={styles.overlay} role="status" aria-live="polite">
      <div className={styles.card}>
        <p className={styles.line1}>Please wait a moment!</p>
        <p className={styles.line2}>We are preparing everything for you.</p>
        <div className={styles.bar}>
          <span className={styles.knob} />
        </div>
      </div>
    </div>
  )
}
