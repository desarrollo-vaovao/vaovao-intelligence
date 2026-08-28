"use client";
import Shell from "@/lib/Shell";
import ConexionMetaPanel from "@/lib/ConexionMetaPanel";

// Ruta directa a Conexión Meta — se conserva porque Leads y Reportes
// enlazan aquí cuando Meta no está conectado ("Conectar ahora →"). El
// contenido real vive en ConexionMetaPanel, compartido con la pestaña
// "Conexión Meta" dentro de /ajustes.
export default function ConexionPage() {
  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Conexión Meta</h1>
          <p>Conecta tu Facebook (recomendado) o usa tokens de System User centrales.</p>
        </div>
      </div>
      <ConexionMetaPanel />
    </Shell>
  );
}
