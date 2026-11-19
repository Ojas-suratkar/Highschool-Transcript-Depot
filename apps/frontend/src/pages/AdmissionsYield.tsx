import { useRef, useState, useEffect } from 'react';
import { Upload, Goal, CheckCircle2, Users, Percent, Award, FileSpreadsheet, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { PageHeader } from '@/components/shared/PageHeader';
import { Button } from '@/components/ui/button';
import { StatCard } from '@/components/shared/StatCard';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { cn } from '@/lib/utils';
import { SpreadsheetImportDialog, ImportContext } from '@/components/shared/SpreadsheetImportDialog';
import { SpreadsheetPreviewDialog } from '@/components/shared/SpreadsheetPreviewDialog';
import { parseSpreadsheet, pickField, pickNumber, ParsedSheet } from '@/lib/excel';

interface YieldData {
  id: string;
  college: string;
  department: string;
  major: string;
  semester: string;
  goal: number;
  admitted: number;
  deposited: number;
  yield: number;
  delta: number;
}

const STORAGE_KEY = 'th_admission_yield_v1';
const FILE_KEY = 'th_admission_yield_file_v1';

function loadYield(): YieldData[] {
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

export default function AdmissionsYield({ embedded = false }: { embedded?: boolean }) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [data, setData] = useState<YieldData[]>(loadYield);

  const [pendingSheet, setPendingSheet] = useState<ParsedSheet | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [lastFile, setLastFile] = useState<ParsedSheet | null>(loadFile);
  const [previewOpen, setPreviewOpen] = useState(false);

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(data)); } catch { /* ignore */ }
  }, [data]);
  useEffect(() => {
    try {
      if (lastFile) localStorage.setItem(FILE_KEY, JSON.stringify(lastFile));
      else localStorage.removeItem(FILE_KEY);
    } catch { /* ignore */ }
  }, [lastFile]);

  const totalGoal = data.reduce((sum, d) => sum + d.goal, 0);
  const totalAdmitted = data.reduce((sum, d) => sum + d.admitted, 0);
  const totalDeposited = data.reduce((sum, d) => sum + d.deposited, 0);
  const overallYield = totalAdmitted ? Math.round((totalDeposited / totalAdmitted) * 100) : 0;
  const goalAttainment = totalGoal ? Math.round((totalDeposited / totalGoal) * 100) : 0;

  const handleDelete = (id: string) => setData((prev) => prev.filter((d) => d.id !== id));

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
    const imported: YieldData[] = sheet.rows.map((row, idx) => {
      const goal = pickNumber(row, ['target', 'goal', 'seats', 'capacity']);
      const admitted = pickNumber(row, ['admitted', 'admits', 'accepted']);
      const deposited = pickNumber(row, ['deposited', 'enrolled', 'committed', 'deposits']);
      const yieldPct = pickNumber(row, ['yield', 'yield%', 'yield %']) || (admitted ? (deposited / admitted) * 100 : 0);
      return {
        id: `${Date.now()}-${idx}`,
        college: pickField(row, ['college', 'school']) || ctx.college || '—',
        department: pickField(row, ['department', 'dept']) || ctx.department || '—',
        major: pickField(row, ['major', 'program', 'course']) || ctx.major || '—',
        semester: pickField(row, ['semester', 'term']) || ctx.term || '—',
        goal,
        admitted,
        deposited,
        yield: yieldPct,
        delta: deposited - goal,
      };
    });
    setData((prev) => [...prev, ...imported]);
    setLastFile(sheet);
    setImportOpen(false);
    setPendingSheet(null);
    toast.success(`Imported ${imported.length} yield row${imported.length === 1 ? '' : 's'} from ${sheet.fileName}`);
  };

  const columns: ColumnDef<YieldData>[] = [
    { header: 'College', accessor: 'college' },
    { header: 'Department', accessor: 'department' },
    { header: 'Major', accessor: 'major' },
    { header: 'Semester', accessor: 'semester' },
    { header: 'Target', accessor: 'goal' },
    { header: 'Admitted', accessor: 'admitted' },
    { header: 'Deposited', accessor: 'deposited' },
    {
      header: 'Yield %',
      accessor: (row) => `${row.yield.toFixed(1)}%`,
    },
    {
      header: 'Delta',
      accessor: (row) => (
        <span className={cn(row.delta < 0 ? 'text-destructive' : 'text-success')}>
          {row.delta > 0 ? '+' : ''}
          {row.delta}
        </span>
      ),
    },
    {
      header: 'Actions',
      accessor: (row) => (
        <Button size="icon" variant="ghost" onClick={() => handleDelete(row.id)}>
          <Trash2 className="h-4 w-4 text-destructive" />
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      {!embedded && (
        <PageHeader
          title="Admission Yield"
          subtitle="Track the admissions funnel — admitted, deposited, and yield against targets"
        />
      )}

      <div className="grid gap-4 md:grid-cols-5">
        <StatCard title="Total Target" value={totalGoal} icon={<Goal className="h-6 w-6" />} accent="blue" />
        <StatCard title="Admitted" value={totalAdmitted} icon={<CheckCircle2 className="h-6 w-6" />} accent="green" />
        <StatCard title="Deposited" value={totalDeposited} icon={<Users className="h-6 w-6" />} accent="violet" />
        <StatCard title="Overall Yield %" value={`${overallYield}%`} icon={<Percent className="h-6 w-6" />} accent="cyan" />
        <StatCard
          title="Target Attainment %"
          value={`${goalAttainment}%`}
          icon={<Award className="h-6 w-6" />}
          accent={goalAttainment >= 100 ? 'green' : 'amber'}
        />
      </div>

      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => fileInputRef.current?.click()}>
          <Upload className="h-4 w-4 mr-2" />
          Upload Yield
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
      </div>

      <DataTable
        columns={columns}
        data={data}
        keyExtractor={(row) => row.id}
        emptyMessage="No yield data yet — upload a yield spreadsheet to get started."
      />

      <SpreadsheetImportDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        sheet={pendingSheet}
        title="Import Admission Yield"
        confirmLabel="Import Yield"
        onImport={handleImport}
      />

      <SpreadsheetPreviewDialog open={previewOpen} onOpenChange={setPreviewOpen} sheet={lastFile} />
    </div>
  );
}
