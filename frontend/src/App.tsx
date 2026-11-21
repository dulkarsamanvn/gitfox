import { API_BASE_URL } from './api/client';
import type { HealthEndpoint, ServiceStatus } from './api/status';
import { useServiceStatus } from './hooks/useServiceStatus';
import { PrPreview } from './components/PrPreview';

type IconName = 'check' | 'refresh' | 'api' | 'database' | 'arrow' | 'alert';

function Icon({ name, className = '' }: { name: IconName; className?: string }) {
  const paths = {
    check: <path d="m5 12 4 4L19 6" />,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6.2 6.2A8 8 0 0 1 20 12M4 12a8 8 0 0 0 13.8 5.8" /></>,
    api: <><path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-13-2 16" /></>,
    database: <><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></>,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    alert: <><path d="m12 3 10 18H2L12 3Z" /><path d="M12 9v5m0 3v.1" /></>,
  };

  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[name]}
    </svg>
  );
}

function ServiceCard({ title, kind, endpoint, status }: {
  title: string;
  kind: 'api' | 'database';
  endpoint: HealthEndpoint;
  status: ServiceStatus;
}) {
  const label = status.state === 'checking'
    ? 'Checking'
    : status.state === 'unhealthy'
      ? 'Unavailable'
      : kind === 'api' ? 'Running' : 'Connected';

  return (
    <section className={`service-card service-card--${status.state}`} aria-labelledby={`${kind}-title`}>
      <div className="card-top">
        <div className="service-icon"><Icon name={kind} /></div>
        <span className={`status-pill status-pill--${status.state}`}>
          <span className="status-dot" />{label}
        </span>
      </div>
      <h3 id={`${kind}-title`}>{title}</h3>
      <p className="service-description">{kind === 'api' ? 'The connection to your backend.' : 'The connection to your review storage.'}</p>
      <p className="service-detail">{status.detail}</p>
      <div className="endpoint-row">
        <span className="method-label">GET</span>
        <code>{endpoint}</code>
        <span className="endpoint-caption">{kind === 'api' ? 'API liveness' : 'Database readiness'}</span>
      </div>
    </section>
  );
}

export default function App() {
  const api = useServiceStatus('/health');
  const database = useServiceStatus('/ready');
  const checks = { api: api.status, database: database.status };
  const lastCheckedAt = Math.max(api.checkedAt, database.checkedAt);
  const lastChecked = lastCheckedAt ? new Date(lastCheckedAt) : null;
  const isChecking = checks.api.state === 'checking' || checks.database.state === 'checking';
  const healthyCount = Number(checks.api.state === 'healthy') + Number(checks.database.state === 'healthy');

  function runChecks() {
    void api.refetch();
    void database.refetch();
  }

  const headline = isChecking
    ? 'Checking your setup.'
    : healthyCount === 2
      ? 'Your setup is ready.'
      : healthyCount === 1
        ? 'One service needs attention.'
        : 'Your services need attention.';
  const summary = isChecking
    ? 'Getting the latest status of your API and database.'
    : healthyCount === 2
      ? 'The API is responding and PostgreSQL is connected.'
      : 'Check the services below, then try again.';
  const overallState = isChecking ? 'checking' : healthyCount === 2 ? 'healthy' : 'unhealthy';

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="GitFox home">
          <img src="/favicon.svg" width="36" height="36" alt="" />
          <span>gitfox<span className="brand-dot">.</span></span>
        </a>
        <span className="environment-label"><span />Local environment</span>
      </header>

      <main>
        <PrPreview />
        <section className="system-status" aria-labelledby="system-status-title" aria-busy={isChecking}>
        <div className="page-heading">
          <div>
            <p className="eyebrow">WORKSPACE OVERVIEW</p>
            <h2 className="page-label" id="system-status-title">System status</h2>
          </div>
          <button className="refresh-button" type="button" onClick={() => void runChecks()} disabled={isChecking}>
            <Icon name="refresh" className={isChecking ? 'spinning' : ''} />
            {isChecking ? 'Checking…' : 'Check again'}
          </button>
        </div>

        <div className={`summary summary--${overallState}`} role="status" aria-live="polite" aria-atomic="true">
          <div className="summary-icon"><Icon name={isChecking ? 'refresh' : healthyCount === 2 ? 'check' : 'alert'} className={isChecking ? 'spinning' : ''} /></div>
          <div className="summary-copy">
            <h3>{headline}</h3>
            <p>{summary}</p>
          </div>
          <span className="summary-count">{isChecking ? 'Checking services' : `${healthyCount} of 2 services ready`}</span>
        </div>

        <div className="services-grid">
          <ServiceCard title="API server" kind="api" endpoint="/health" status={checks.api} />
          <ServiceCard title="PostgreSQL database" kind="database" endpoint="/ready" status={checks.database} />
        </div>

        <div className="check-metadata">
          <span><span className="metadata-dot" />{isChecking ? 'Checking services…' : lastChecked ? `Last checked at ${lastChecked.toLocaleTimeString()}` : 'Waiting for the first check'}</span>
          <span className="backend-address">Backend <code>{API_BASE_URL}</code></span>
        </div>

        <section className="explanation" aria-labelledby="explanation-title">
          <div>
            <h3 id="explanation-title">How the checks work</h3>
            <p>Your browser asks FastAPI for each status. FastAPI checks PostgreSQL.</p>
          </div>
          <div className="connection-flow" aria-label="Browser connects to FastAPI, which connects to PostgreSQL">
            <span>Browser</span><Icon name="arrow" /><span>FastAPI</span><Icon name="arrow" /><span>PostgreSQL</span>
          </div>
        </section>
        </section>
      </main>

      <footer className="site-footer">
        <span>GitFox development workspace</span>
        <span>AI-powered code review</span>
      </footer>
    </div>
  );
}
