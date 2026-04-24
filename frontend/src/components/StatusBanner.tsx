export function StatusBanner({
  kind,
  title,
  detail,
}: {
  kind: 'info' | 'error' | 'success' | 'warning';
  title: string;
  detail?: string;
}) {
  return (
    <div className={`banner banner-${kind}`} role="status">
      <strong>{title}</strong>
      {detail ? <p className="banner-detail">{detail}</p> : null}
    </div>
  );
}
