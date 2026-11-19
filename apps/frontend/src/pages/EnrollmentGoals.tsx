import { useState, useRef, useEffect } from 'react';
import { Plus, Upload, Trash2, Goal, Users, BarChart3, FileSpreadsheet } from 'lucide-react';
import { toast } from 'sonner';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatCard } from '@/components/shared/StatCard';
import { Button } from '@/components/ui/button';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { TermSelector } from '@/components/shared/TermSelector';
import { SpreadsheetImportDialog, ImportContext } from '@/components/shared/SpreadsheetImportDialog';
import { SpreadsheetPreviewDialog } from '@/components/shared/SpreadsheetPreviewDialog';
import { parseSpreadsheet, pickField, pickNumber, ParsedSheet } from '@/lib/excel';

interface EnrollmentGoal {
  id: string;
  college: string;
  department: string;
  major: string;
  semester: string;
  goal: number;
  notes: string;
}

const STORAGE_KEY = 'th_enrollment_targets_v1';
const FILE_KEY = 'th_enrollment_targets_file_v1';

function loadGoals(): EnrollmentGoal[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return [];
}

function loadFile(): ParsedSheet | null {
  try {
    const raw = localStorage.getItem(FILE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return null;
}

export default function EnrollmentGoals({ embedded = false }: { embedded?: boolean }) {
  const [goals, setGoals] = useState<EnrollmentGoal[]>(loadGoals);
  const [showDialog, setShowDialog] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Excel import + preview state.
  const [pendingSheet, setPendingSheet] = useState<ParsedSheet | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [lastFile, setLastFile] = useState<ParsedSheet | null>(loadFile);
  const [previewOpen, setPreviewOpen] = useState(false);

  const [newGoal, setNewGoal] = useState({
    college: '',
    department: '',
    major: '',
    semester: '',
    goal: '' as string,
    notes: '',
  });

  // Persist targets + last uploaded file so the page survives a refresh.
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(goals)); } catch { /* ignore */ }
  }, [goals]);
  useEffect(() => {
    try {
      if (lastFile) localStorage.setItem(FILE_KEY, JSON.stringify(lastFile));
      else localStorage.removeItem(FILE_KEY);
    } catch { /* ignore */ }
  }, [lastFile]);

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
    setNewGoal({ college: '', department: '', major: '', semester: '', goal: '', notes: '' });
    setShowDialog(false);
  };

  const handleFilePicked = async (file: File) => {
    try {
      const sheet = await parseSpreadsheet(file);
      if (sheet.rows.length === 0) {
        toast.error('No rows found in that file. Check that the first row has column headers.');
        return;
      }
      setPendingSheet(sheet);
      setImportOpen(true);
    } catch {
      toast.error('Could not read that file. Please upload a valid Excel or CSV file.');
    }
  };

  const handleImport = (sheet: ParsedSheet, ctx: ImportContext) => {
    const imported: EnrollmentGoal[] = sheet.rows.map((row, idx) => ({
      id: `${Date.now()}-${idx}`,
      college: pickField(row, ['college', 'school']) || ctx.college || '—',
      department: pickField(row, ['department', 'dept']) || ctx.department || '—',
      major: pickField(row, ['major', 'program', 'course']) || ctx.major || '—',
      semester: pickField(row, ['semester', 'term']) || ctx.term || '—',
      goal: pickNumber(row, ['target', 'goal', 'seats', 'capacity']),
      notes: pickField(row, ['notes', 'note', 'comment']) || ctx.notes || '',
    }));
    setGoals((prev) => [...prev, ...imported]);
    setLastFile(sheet);
    setImportOpen(false);
    setPendingSheet(null);
    toast.success(`Imported ${imported.length} target${imported.length === 1 ? '' : 's'} from ${sheet.fileName}`);
  };

  const columns: ColumnDef<EnrollmentGoal>[] = [
    { header: 'College', accessor: 'college' },
    { header: 'Department', accessor: 'department' },
    { header: 'Major', accessor: 'major' },
    { header: 'Semester', accessor: 'semester' },
    { header: 'Target', accessor: 'goal' },
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
      {!embedded && (
        <PageHeader
          title="Enrollment Targets"
          subtitle="Set and track enrollment targets"
        />
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <StatCard title="Total Targets" value={totalGoals} icon={<Goal className="h-6 w-6" />} accent="blue" />
        <StatCard title="Total Seats" value={totalTarget} icon={<Users className="h-6 w-6" />} accent="green" />
        <StatCard title="Avg per Program" value={avgPerProgram} icon={<BarChart3 className="h-6 w-6" />} accent="violet" />
      </div>

      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => fileInputRef.current?.click()}>
          <Upload className="h-4 w-4 mr-2" />
          Upload Targets
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,.xls,.csv"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.currentTarget.value = '';
            if (file) handleFilePicked(file);
          }}
        />
        {lastFile && (
          <Button variant="outline" onClick={() => setPreviewOpen(true)}>
            <FileSpreadsheet className="h-4 w-4 mr-2" />
            View File
          </Button>
        )}
        <Button onClick={() => setShowDialog(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Add Target
        </Button>
      </div>

      <DataTable
        columns={columns}
        data={goals}
        keyExtractor={(row) => row.id}
        emptyMessage="No enrollment targets yet — upload an Excel file or add one manually."
      />

      <SpreadsheetImportDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        sheet={pendingSheet}
        title="Import Enrollment Targets"
        confirmLabel="Import Targets"
        onImport={handleImport}
      />

      <SpreadsheetPreviewDialog open={previewOpen} onOpenChange={setPreviewOpen} sheet={lastFile} />

      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Enrollment Target</DialogTitle>
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
              <Label>Target</Label>
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
            <Button onClick={handleAddGoal}>Add Target</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
