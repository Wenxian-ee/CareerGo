export function StatusBanner({
  kind,
  title,
  detail,
}: {
  kind: 'info' | 'error' | 'success' | 'warning';
  title: string;
  detail?: string;
}) {
  const isAssertive = kind === 'error' || kind === 'warning';
  return (
    <div
      className={`banner banner-${kind}`}
      role={isAssertive ? 'alert' : 'status'}
      aria-live={isAssertive ? 'assertive' : 'polite'}
    >
      <strong>{title}</strong>
      {detail ? <p className="banner-detail">{detail}</p> : null}
    </div>
  );
}
