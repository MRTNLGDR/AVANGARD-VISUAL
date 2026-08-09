import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchGovernanceSnapshot } from "../services/governance-service";

export default function GovernanceScreen() {
  const query = useQuery({
    queryKey: ["governance", "snapshot"],
    queryFn: fetchGovernanceSnapshot,
    staleTime: 0,
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
  });

  useEffect(() => {
    const onGovernanceChanged = () => void query.refetch();
    window.addEventListener("oraculo:governance-updated", onGovernanceChanged);
    const events = new EventSource("/api/events");
    events.addEventListener("governance.updated", onGovernanceChanged);
    return () => {
      window.removeEventListener("oraculo:governance-updated", onGovernanceChanged);
      events.close();
    };
  }, [query.refetch]);

  if (query.isLoading) return <div>Carregando governança...</div>;
  if (query.isError || !query.data) return <div>Governança indisponível</div>;

  const data = query.data;
  const pendingTasks = data.tasks.filter((task) => task.status === "PENDING").slice(0, 12);
  const openAlerts = data.alerts.filter((alert) => alert.status === "OPEN").slice(0, 10);

  return (
    <section>
      <header>
        <h1>Governança</h1>
        <button type="button" onClick={() => void query.refetch()}>Atualizar</button>
        <span>Estado: {data.state}</span>
      </header>
      <div>
        <h2>Progresso global</h2>
        <p>Concluídas: {data.summary.doneTasks}</p>
        <p>Pendentes: {data.summary.pendingTasks}</p>
        <p>Alertas: {data.summary.openAlerts}</p>
        <p>Progresso: {data.summary.progressPercent.toFixed(2)}%</p>
      </div>
      <div>
        <h2>Módulos</h2>
        <ul>{data.modules.map((module) => <li key={module.module_id}><strong>{module.module_id}</strong> {module.module_title} — {module.done}/{module.total}</li>)}</ul>
      </div>
      <div>
        <h2>Próximas tarefas reais</h2>
        <ul>{pendingTasks.map((task) => <li key={task.id}><strong>{task.id}</strong> - {task.title} [{task.category}]<br /><small>{task.source_path}:{task.source_line}</small></li>)}</ul>
      </div>
      <div>
        <h2>Alertas, bugs e gaps</h2>
        <ul>{openAlerts.map((alert) => <li key={alert.id}>{alert.id} {alert.severity} — {alert.kind}<br />{alert.fact}<br /><em>Ação: {alert.action}</em></li>)}</ul>
      </div>
    </section>
  );
}
