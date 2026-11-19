import { PageHeader } from '@/components/shared/PageHeader';
import { BarChart3 } from 'lucide-react';
import AdmissionsDashboard from './AdmissionsDashboard';

export default function ReportsInsights() {
  return (
    <div className="space-y-5">
      <PageHeader
        title="Reports & Insights"
        icon={BarChart3}
        iconColor="text-violet-600"
        subtitle="Dashboards summarizing admission decisions across programs and terms"
      />
      <AdmissionsDashboard />
    </div>
  );
}
