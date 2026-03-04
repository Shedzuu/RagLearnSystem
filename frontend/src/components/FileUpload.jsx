import { useState, useRef } from 'react'
import styles from './FileUpload.module.css'

/**
 * Зона выбора файла или перетаскивания.
 * onFileSelect(file) — вызывается при выборе/дропе файла.
 */
export default function FileUpload({ onFileSelect }) {
  const [drag, setDrag] = useState(false)
  const inputRef = useRef(null)

  const handleFile = (file) => {
    if (!file) return
    if (onFileSelect) onFileSelect(file)
  }

  const onDrop = (e) => {
    e.preventDefault()
    setDrag(false)
    const file = e.dataTransfer?.files?.[0]
    handleFile(file)
  }

  const onDragOver = (e) => {
    e.preventDefault()
    setDrag(true)
  }

  const onDragLeave = () => setDrag(false)

  const onInputChange = (e) => {
    const file = e.target?.files?.[0]
    handleFile(file)
    e.target.value = ''
  }

  const openPicker = () => inputRef.current?.click()

  return (
    <>
      <div
        className={`${styles.zone} ${drag ? styles.drag : ''}`}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
      >
        <input
          ref={inputRef}
          type="file"
          className={styles.input}
          onChange={onInputChange}
          accept=".pdf,.doc,.docx,.txt"
          aria-label="Choose file"
        />
        <img src="/assets/upload_arrow.png" alt="" className={styles.uploadIcon} />
        <button type="button" className={styles.button} onClick={openPicker}>
          <img src="/assets/document_file.png" alt="" className={styles.docIcon} />
          Choose file
        </button>
        <p className={styles.hint}>Or drag and drop a file</p>
      </div>
    </>
  )
}
