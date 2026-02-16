import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatCard } from '@/components/shared/StatCard';
import { FileText, TrendingUp } from 'lucide-react';

export default function DesignSystemTest() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Design System Test"
        subtitle="Verify all design system elements are working correctly"
      />

      {/* Color Swatches */}
      <Card>
        <CardHeader>
          <CardTitle>Color Palette</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-4 gap-4">
            <div>
              <div className="h-20 rounded-lg bg-sidebar mb-2"></div>
              <p className="text-sm font-medium">Sidebar</p>
              <p className="text-xs text-muted-foreground">hsl(220, 60%, 20%)</p>
            </div>
            <div>
              <div className="h-20 rounded-lg bg-green-100 border border-green-200 mb-2"></div>
              <p className="text-sm font-medium">Success</p>
              <p className="text-xs text-muted-foreground">#22c55e</p>
            </div>
            <div>
              <div className="h-20 rounded-lg bg-red-100 border border-red-200 mb-2"></div>
              <p className="text-sm font-medium">Error</p>
              <p className="text-xs text-muted-foreground">#ef4444</p>
            </div>
            <div>
              <div className="h-20 rounded-lg bg-amber-100 border border-amber-200 mb-2"></div>
              <p className="text-sm font-medium">Warning</p>
              <p className="text-xs text-muted-foreground">#f59e0b</p>
            </div>
            <div>
              <div className="h-20 rounded-lg bg-blue-100 border border-blue-200 mb-2"></div>
              <p className="text-sm font-medium">Info</p>
              <p className="text-xs text-muted-foreground">#3b82f6</p>
            </div>
            <div>
              <div className="h-20 rounded-lg bg-gradient-to-br from-blue-400 to-blue-600 mb-2"></div>
              <p className="text-sm font-medium">Logo Gradient</p>
              <p className="text-xs text-muted-foreground">Blue gradient</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Status Badges */}
      <Card>
        <CardHeader>
          <CardTitle>Status Badges</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            <StatusBadge status="processing" />
            <StatusBadge status="processed" />
            <StatusBadge status="failed" />
            <StatusBadge status="warning" />
            <StatusBadge status="eligible" />
            <StatusBadge status="ineligible" />
            <StatusBadge status="needs_verification" />
            <StatusBadge status="active" />
            <StatusBadge status="revoked" />
          </div>
        </CardContent>
      </Card>

      {/* Buttons */}
      <Card>
        <CardHeader>
          <CardTitle>Buttons with Transitions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            <Button>Primary Button</Button>
            <Button variant="outline">Outline Button</Button>
            <Button variant="secondary">Secondary Button</Button>
            <Button variant="destructive">Destructive Button</Button>
            <Button variant="ghost">Ghost Button</Button>
          </div>
        </CardContent>
      </Card>

      {/* Stat Cards */}
      <Card>
        <CardHeader>
          <CardTitle>Stat Cards</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-3">
            <StatCard
              title="Total Transcripts"
              value={150}
              icon={<FileText className="h-6 w-6" />}
              trend={{ value: 12, isPositive: true }}
            />
            <StatCard
              title="Failed"
              value={5}
              icon={<FileText className="h-6 w-6" />}
              trend={{ value: -3, isPositive: false }}
              className="border-red-200 bg-red-50"
            />
            <StatCard
              title="Success Rate"
              value="96%"
              icon={<TrendingUp className="h-6 w-6" />}
              className="border-green-200 bg-green-50"
            />
          </div>
        </CardContent>
      </Card>

      {/* Typography */}
      <Card>
        <CardHeader>
          <CardTitle>Typography</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Page Title (text-2xl font-bold tracking-tight)</h1>
          </div>
          <div>
            <h2 className="text-lg font-semibold">Card Title (text-lg font-semibold)</h2>
          </div>
          <div>
            <p className="text-sm">Body text (text-sm)</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Muted text (text-sm text-muted-foreground)</p>
          </div>
          <div>
            <code className="font-mono text-sm">Monospace text (font-mono text-sm)</code>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

