import Shell from "./Shell";

export default function ComingSoon({ title, description }) {
  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </div>
      <div className="card empty">
        <h3>Próximamente</h3>
        <p>Esta sección todavía no está disponible.</p>
      </div>
    </Shell>
  );
}
