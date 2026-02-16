import { useState } from 'react';
import { Upload, Eye, Play, Copy, Trash2, Settings } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatCard } from '@/components/shared/StatCard';
import { Button } from '@/components/ui/button';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { Progress } from '@/components/ui/progress';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { TermSelector } from '@/components/shared/TermSelector';

interface Template {
  id: string;
  name: string;
  school: string;
  format: string;
  termId: string;
  uploadedDate: string;
  status: 'pending' | 'training' | 'trained' | 'failed';
  accuracy: number;
  fields: number;
  processed: number;
}

export default function TemplateManager() {
  const [templates] = useState<Template[]>([
    {
      id: '1',
      name: 'Lincoln HS Template',
      school: 'Lincoln High School',
      format: 'PDF',
      termId: 'term-1',
      uploadedDate: '2025-01-10',
      status: 'trained',
      accuracy: 98,
      fields: 12,
      processed: 45,
    },
  ]);
  const [showUploadDialog, setShowUploadDialog] = useState(false);

  const columns: ColumnDef<Template>[] = [
    {
      header: 'Template Name',
      accessor: (row) => (
        <div>
          <div className="font-medium">{row.name}</div>
          <div className="text-sm text-muted-foreground">{row.school}</div>
        </div>
      ),
    },
    { header: 'Format', accessor: 'format' },
    { header: 'Term', accessor: 'termId' },
    { header: 'Uploaded', accessor: 'uploadedDate' },
    {
      header: 'Status',
      accessor: (row) => <StatusBadge status={row.status} />,
    },
    {
      header: 'Accuracy',
      accessor: (row) => (
        <div className="w-24">
          <Progress value={row.accuracy} className="h-2" />
          <span className="text-xs text-muted-foreground">{row.accuracy}%</span>
        </div>
      ),
    },
    { header: 'Fields', accessor: 'fields' },
    { header: 'Processed', accessor: 'processed' },
    {
      header: 'Actions',
      accessor: (row) => (
        <div className="flex gap-1">
          <Button size="icon" variant="ghost">
            <Settings className="h-4 w-4" />
          </Button>
          <Button size="icon" variant="ghost">
            <Eye className="h-4 w-4" />
          </Button>
          {row.status === 'pending' && (
            <Button size="icon" variant="ghost">
              <Play className="h-4 w-4" />
            </Button>
          )}
          <Button size="icon" variant="ghost">
            <Copy className="h-4 w-4" />
          </Button>
          <Button size="icon" variant="ghost">
            <Trash2 className="h-4 w-4 text-destructive" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Template Manager"
        subtitle="Upload and manage transcript templates"
        actionLabel="Upload Template"
        onAction={() => setShowUploadDialog(true)}
      />

      {/* Stat Cards */}
      <div className="grid gap-4 md:grid-cols-5">
        <StatCard title="Total" value={12} icon={<Upload className="h-6 w-6" />} />
        <StatCard title="Trained" value={8} icon={<Play className="h-6 w-6" />} />
        <StatCard title="Training" value={2} icon={<Play className="h-6 w-6" />} />
        <StatCard title="Pending" value={1} icon={<Play className="h-6 w-6" />} />
        <StatCard title="Failed" value={1} icon={<Play className="h-6 w-6" />} />
      </div>

      {/* Templates Table */}
      <DataTable
        columns={columns}
        data={templates}
        keyExtractor={(row) => row.id}
        emptyMessage="No templates uploaded"
      />

      {/* Upload Dialog */}
      <Dialog open={showUploadDialog} onOpenChange={setShowUploadDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Upload Template</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="border-2 border-dashed rounded-lg p-8 text-center">
              <Upload className="h-12 w-12 mx-auto text-muted-foreground mb-2" />
              <p className="text-sm text-muted-foreground">
                Drag and drop PDF template or click to browse
              </p>
            </div>
            <div>
              <Label>Template Name</Label>
              <Input placeholder="e.g., Lincoln HS Template" className="mt-2" />
            </div>
            <div>
              <Label>School/District Name</Label>
              <Input placeholder="e.g., Lincoln High School" className="mt-2" />
            </div>
            <TermSelector value="" onValueChange={() => {}} label="Term" showAddButton={false} />
            <div>
              <Label>Notes (Optional)</Label>
              <Textarea placeholder="Additional information..." className="mt-2" />
            </div>
            <Button className="w-full">Upload Template</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

