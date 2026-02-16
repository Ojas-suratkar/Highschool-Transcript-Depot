import { useState, useRef } from 'react';
import { Plus, Upload, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatCard } from '@/components/shared/StatCard';
import { Button } from '@/components/ui/button';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { TermSelector } from '@/components/shared/TermSelector';

interface EnrollmentGoal {
  id: string;
  college: string;
  department: string;
  major: string;
  semester: string;
  goal: number;
  notes: string;
}

export default function EnrollmentGoals() {
  const [goals, setGoals] = useState<EnrollmentGoal[]>([
    {
      id: '1',
      college: 'Engineering',
      department: 'Computer Science',
      major: 'Computer Science (MS)',
      semester: 'Fall 2025',
      goal: 50,
      notes: 'Increased capacity',
    },
  ]);
  const [showDialog, setShowDialog] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [newGoal, setNewGoal] = useState({
    college: '',
    department: '',
    major: '',
    semester: '',
    goal: '' as string,
    notes: '',
  });

  const totalGoals = goals.length;
  const totalTarget = goals.reduce((sum, g) => sum + g.goal, 0);
  const avgPerProgram = totalGoals ? Math.round(totalTarget / totalGoals) : 0;

  const handleDelete = (id: string) => {
    setGoals((prev) => prev.filter((g) => g.id !== id));
  };

  const handleAddGoal = () => {
    const parsed = Number(newGoal.goal || 0);
    const goalObj: EnrollmentGoal = {
      id: Date.now().toString(),
      college: newGoal.college || '—',
      department: newGoal.department || '—',
      major: newGoal.major || '—',
      semester: newGoal.semester || '—',
      goal: Number.isFinite(parsed) ? parsed : 0,
      notes: newGoal.notes || '',
    };
    setGoals((prev) => [...prev, goalObj]);
    // reset form and close dialog
    setNewGoal({ college: '', department: '', major: '', semester: '', goal: '', notes: '' });
    setShowDialog(false);
  };

  const columns: ColumnDef<EnrollmentGoal>[] = [
    { header: 'College', accessor: 'college' },
    { header: 'Department', accessor: 'department' },
    { header: 'Major', accessor: 'major' },
    { header: 'Semester', accessor: 'semester' },
    { header: 'Goal', accessor: 'goal' },
    { header: 'Notes', accessor: 'notes' },
    {
      header: 'Actions',
      accessor: (row) => (
        <div className="flex gap-1">
          <Button size="icon" variant="ghost" onClick={() => handleDelete(row.id)}>
            <Trash2 className="h-4 w-4 text-destructive" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Enrollment Targets"
        subtitle="Set and track enrollment targets"
      />

      <div className="grid gap-4 md:grid-cols-3">
        <StatCard title="Total Goals" value={totalGoals} icon={<Plus className="h-6 w-6" />} />
        <StatCard title="Total Target" value={totalTarget} icon={<Plus className="h-6 w-6" />} />
        <StatCard title="Avg per Program" value={avgPerProgram} icon={<Plus className="h-6 w-6" />} />
      </div>

      <div className="flex gap-2">
        <Button variant="outline" onClick={() => fileInputRef.current?.click()}>
          <Upload className="h-4 w-4 mr-2" />
          Upload Goals
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={(e) => {
            const files = e.target.files;
            if (!files || files.length === 0) return;
            const names = Array.from(files).map((f) => f.name).join(', ');
            toast.success(`Selected ${files.length} file(s): ${names}`);
            // leave actual file processing to future implementation
            // reset input so same file can be selected again
            e.currentTarget.value = '';
          }}
        />
        <Button onClick={() => setShowDialog(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Add Goal
        </Button>
      </div>

      <DataTable
        columns={columns}
        data={goals}
        keyExtractor={(row) => row.id}
        emptyMessage="No enrollment goals set"
      />

      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Enrollment Goal</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>College</Label>
              <Input placeholder="e.g., Engineering" className="mt-2" value={newGoal.college} onChange={(e) => setNewGoal({ ...newGoal, college: e.target.value })} />
            </div>
            <div>
              <Label>Department</Label>
              <Input placeholder="e.g., Computer Science" className="mt-2" value={newGoal.department} onChange={(e) => setNewGoal({ ...newGoal, department: e.target.value })} />
            </div>
            <div>
              <Label>Major</Label>
              <Input placeholder="e.g., Computer Science (MS)" className="mt-2" value={newGoal.major} onChange={(e) => setNewGoal({ ...newGoal, major: e.target.value })} />
            </div>
            <div>
              <Label>Goal</Label>
              <Input type="number" placeholder="50" className="mt-2" value={newGoal.goal} onChange={(e) => setNewGoal({ ...newGoal, goal: e.target.value })} />
            </div>
            <TermSelector value={newGoal.semester} onValueChange={(v) => setNewGoal({ ...newGoal, semester: v })} label="Term" showAddButton={false} />
            <div>
              <Label>Notes</Label>
              <Input placeholder="Optional notes" className="mt-2" value={newGoal.notes} onChange={(e) => setNewGoal({ ...newGoal, notes: e.target.value })} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleAddGoal}>Add Goal</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

