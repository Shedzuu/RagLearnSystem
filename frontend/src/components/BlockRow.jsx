import styles from './BlockRow.module.css'

export default function BlockRow({ items, variant = 'gray' }) {
  return (
    <div className={styles.row}>
      {items.map((item, i) => (
        <div key={i} className={styles.block}>
          <div className={variant === 'white' ? styles.placeholderWhite : styles.placeholderGray}>
            {item.image ? (
              <img src={item.image} alt={item.title || 'Preview'} className={styles.image} />
            ) : (
              <span className={styles.fallback}>photo</span>
            )}
          </div>
          {item.title && <p className={styles.title}>{item.title}</p>}
          {item.text && <p className={styles.text}>{item.text}</p>}
        </div>
      ))}
    </div>
  )
}
