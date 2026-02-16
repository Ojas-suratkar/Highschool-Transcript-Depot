import { useState } from 'react';
import { FileUp, RefreshCw, Pencil, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { useTerm } from '@/contexts/TermContext';
import { toast } from 'sonner';

interface CloudFolder {
  id: string;
  label: string;
  link: string;
  semester: string;
  added: string;
  lastPolled: string;
}

export default function CloudFolders() {
  const { terms } = useTerm();
  const [folders, setFolders] = useState<CloudFolder[]>([
    {
      id: '1',
      label: 'Fall 2024 Transcripts',
      link: 'https://drive.google.com/drive/folders/1abc123def456ghi789jkl',
      semester: 'fall-2024',
      added: '2024-01-15',
      lastPolled: '2 hours ago',
    },
    {
      id: '2',
      label: 'Spring 2025 Applications',
      link: 'https://drive.google.com/drive/folders/2xyz789abc123def456ghi',
      semester: 'spring-2025',
      added: '2024-02-01',
      lastPolled: '1 day ago',
    },
  ]);

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [editingFolder, setEditingFolder] = useState<CloudFolder | null>(null);
  const [formData, setFormData] = useState({
    label: '',
    link: '',
    semester: '',
  });

  const handleOpenDialog = (folder?: CloudFolder) => {
    if (folder) {
      setEditingFolder(folder);
      setFormData({
        label: folder.label,
        link: folder.link,
        semester: folder.semester,
      });
    } else {
      setEditingFolder(null);
      setFormData({ label: '', link: '', semester: '' });
    }
    setIsDialogOpen(true);
  };

  const handleSaveFolder = () => {
    if (editingFolder) {
      // Update existing folder
      setFolders(folders.map(f =>
        f.id === editingFolder.id
          ? { ...f, ...formData }
          : f
      ));
      toast.success('Folder updated successfully');
    } else {
      // Add new folder
      const newFolder: CloudFolder = {
        id: Date.now().toString(),
        ...formData,
        added: new Date().toISOString().split('T')[0],
        lastPolled: 'Never',
      };
      setFolders([...folders, newFolder]);
      toast.success('Folder added successfully');
    }
    setIsDialogOpen(false);
  };

  const handleExtract = (folder: CloudFolder) => {
    toast.success(`Extracting transcripts from ${folder.label}...`);
  };

  const handlePollNow = (folder: CloudFolder) => {
    setFolders(folders.map(f =>
      f.id === folder.id
        ? { ...f, lastPolled: 'Just now' }
        : f
    ));
    toast.success('Polling folder for new transcripts');
  };

  const handleDelete = (folder: CloudFolder) => {
    setFolders(folders.filter(f => f.id !== folder.id));
    toast.success('Folder deleted');
  };

  const columns: ColumnDef<CloudFolder>[] = [
    {
      header: 'Label',
      accessor: 'label',
    },
    {
      header: 'Link',
      accessor: 'link',
      cell: (value: string) => (
        <a
          href={value}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline block max-w-[200px] truncate"
          title={value}
        >
          {value}
        </a>
      ),
    },
    {
      header: 'Semester',
      accessor: 'semester',
      cell: (value: string) => {
        const term = terms.find(t => t.id === value);
        return term?.name || value;
      },
    },
    {
      header: 'Added',
      accessor: 'added',
    },
    {
      header: 'Last Polled',
      accessor: 'lastPolled',
    },
    {
      header: 'Actions',
      accessor: (row) => row,
      cell: (_, row: CloudFolder) => (
        <TooltipProvider>
          <div className="flex gap-1">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => handleExtract(row)}
                  className="h-8 w-8 text-blue-600 hover:text-blue-700 hover:bg-blue-50"
                >
                  <FileUp className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Extract transcripts</TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => handlePollNow(row)}
                  className="h-8 w-8"
                >
                  <RefreshCw className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Poll now</TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => handleOpenDialog(row)}
                  className="h-8 w-8"
                >
                  <Pencil className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Edit</TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => handleDelete(row)}
                  className="h-8 w-8 text-red-600 hover:text-red-700 hover:bg-red-50"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Delete</TooltipContent>
            </Tooltip>
          </div>
        </TooltipProvider>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Cloud Folders"
        subtitle="Manage cloud folder links for transcript polling"
        actionLabel="Add Folder Link"
        onAction={() => handleOpenDialog()}
      />

      <DataTable
        columns={columns}
        data={folders}
        keyExtractor={(row) => row.id}
        emptyMessage="No cloud folders configured"
      />

      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingFolder ? 'Edit Folder' : 'Add Folder Link'}</DialogTitle>
            <DialogDescription>
              {editingFolder ? 'Update the cloud folder details' : 'Add a new cloud folder link to poll for transcripts'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="label">Label</Label>
              <Input
                id="label"
                placeholder="e.g., Fall 2024 Transcripts"
                value={formData.label}
                onChange={(e) => setFormData({ ...formData, label: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="url">URL</Label>
              <Input
                id="url"
                placeholder="https://drive.google.com/..."
                value={formData.link}
                onChange={(e) => setFormData({ ...formData, link: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="term">Term</Label>
              <select
                id="term"
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={formData.semester}
                onChange={(e) => setFormData({ ...formData, semester: e.target.value })}
              >
                <option value="">Select term</option>
                {terms.map((term) => (
                  <option key={term.id} value={term.id}>
                    {term.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleSaveFolder}>
              {editingFolder ? 'Update' : 'Add'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

