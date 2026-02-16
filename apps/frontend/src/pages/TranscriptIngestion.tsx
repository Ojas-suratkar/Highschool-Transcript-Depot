import { useState, useEffect, useCallback } from 'react';
import {
  Upload,
  Cloud,
  FileText,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  RefreshCw,
  MoreVertical,
  Pause,
  Play,
  Trash2,
  Plus,
  Download,
  Eye,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import { useToast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';
import {
  getCloudFolders,
  addCloudFolder,
  pollCloudFolder,
  getRecentUploads,
  uploadTranscript,
} from '@/lib/admissionsApi';
import type { CloudFolderSource, TranscriptUpload } from '@/types/admissions';

export default function TranscriptIngestion() {
  const { toast } = useToast();
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [pollingId, setPollingId] = useState<string | null>(null);
  const [cloudFolders, setCloudFolders] = useState<CloudFolderSource[]>([]);
  const [recentUploads, setRecentUploads] = useState<TranscriptUpload[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [newFolder, setNewFolder] = useState({
    name: '',
    url: '',
    provider: 'google_drive' as CloudFolderSource['provider'],
  });

  useEffect(() => {
    Promise.all([getCloudFolders(), getRecentUploads()]).then(([folders, uploads]) => {
      setCloudFolders(folders);
      setRecentUploads(uploads);
      setLoading(false);
    });
  }, []);

  const handleFileUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (!files || files.length === 0) return;

      setUploading(true);
      try {
        for (const file of Array.from(files)) {
          await uploadTranscript(file);
        }
        toast({
          title: 'Upload successful',
          description: `${files.length} file(s) uploaded and queued for processing`,
        });
        // Refresh uploads
        const uploads = await getRecentUploads();
        setRecentUploads(uploads);
      } catch (error) {
        toast({
          title: 'Upload failed',
          description: 'There was an error uploading your files',
          variant: 'destructive',
        });
      } finally {
        setUploading(false);
        e.target.value = '';
      }
    },
    [toast]
  );

  const handleAddCloudFolder = async () => {
    if (!newFolder.name || !newFolder.url) {
      toast({
        title: 'Missing information',
        description: 'Please fill in all fields',
        variant: 'destructive',
      });
      return;
    }

    const folder = await addCloudFolder(newFolder);
    setCloudFolders([...cloudFolders, folder]);
    setDialogOpen(false);
    setNewFolder({ name: '', url: '', provider: 'google_drive' });
    toast({
      title: 'Cloud folder added',
      description: 'The folder will be polled for new transcripts',
    });
  };

  const handlePollFolder = async (id: string) => {
    setPollingId(id);
    const result = await pollCloudFolder(id);
    setPollingId(null);
    
    if (result.success) {
      toast({
        title: 'Polling complete',
        description: `Found ${result.filesFound} new file(s)`,
      });
      // Refresh data
      const [folders, uploads] = await Promise.all([getCloudFolders(), getRecentUploads()]);
      setCloudFolders(folders);
      setRecentUploads(uploads);
    }
  };

  const statusConfig = {
    in_queue: { label: 'In Queue', icon: Clock, className: 'text-muted-foreground' },
    processing: { label: 'Processing', icon: Loader2, className: 'text-info' },
    processed: { label: 'Processed', icon: CheckCircle2, className: 'text-success' },
    failed: { label: 'Failed', icon: XCircle, className: 'text-destructive' },
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Transcript Ingestion</h1>
        <p className="text-muted-foreground">Upload transcripts manually or configure cloud folder polling</p>
      </div>

      {/* Manual Upload */}
      <Card className="shadow-card">
        <CardHeader>
          <CardTitle>Manual Upload</CardTitle>
          <CardDescription>Upload transcript PDFs directly from your computer</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="border-2 border-dashed border-border rounded-lg p-8 text-center hover:border-primary/50 transition-colors">
            <Upload className="h-10 w-10 mx-auto mb-3 text-muted-foreground" />
            <h3 className="font-medium mb-1">Drop files here or click to browse</h3>
            <p className="text-sm text-muted-foreground mb-4">Supports PDF files up to 10MB</p>
            <Input
              type="file"
              accept=".pdf"
              multiple
              onChange={handleFileUpload}
              disabled={uploading}
              className="hidden"
              id="file-upload"
            />
            <Button asChild disabled={uploading}>
              <label htmlFor="file-upload" className="cursor-pointer">
                {uploading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Uploading...
                  </>
                ) : (
                  <>
                    <Upload className="mr-2 h-4 w-4" />
                    Select Files
                  </>
                )}
              </label>
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Cloud Folder Polling */}
      <Card className="shadow-card">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Cloud Folder Polling</CardTitle>
              <CardDescription>Automatically poll cloud storage folders for new transcripts</CardDescription>
            </div>
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
              <DialogTrigger asChild>
                <Button>
                  <Plus className="mr-2 h-4 w-4" />
                  Add Folder
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Add Cloud Folder</DialogTitle>
                  <DialogDescription>
                    Configure a cloud storage folder to automatically poll for new transcripts
                  </DialogDescription>
                </DialogHeader>
                <div className="space-y-4 py-4">
                  <div className="space-y-2">
                    <Label htmlFor="folder-name">Folder Name</Label>
                    <Input
                      id="folder-name"
                      placeholder="e.g., Admissions Dropbox"
                      value={newFolder.name}
                      onChange={(e) => setNewFolder({ ...newFolder, name: e.target.value })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="folder-provider">Provider</Label>
                    <Select
                      value={newFolder.provider}
                      onValueChange={(value) =>
                        setNewFolder({ ...newFolder, provider: value as CloudFolderSource['provider'] })
                      }
                    >
                      <SelectTrigger id="folder-provider">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="google_drive">Google Drive</SelectItem>
                        <SelectItem value="dropbox">Dropbox</SelectItem>
                        <SelectItem value="onedrive">OneDrive</SelectItem>
                        <SelectItem value="s3">Amazon S3</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="folder-url">Folder URL</Label>
                    <Input
                      id="folder-url"
                      placeholder="https://..."
                      value={newFolder.url}
                      onChange={(e) => setNewFolder({ ...newFolder, url: e.target.value })}
                    />
                  </div>
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setDialogOpen(false)}>
                    Cancel
                  </Button>
                  <Button onClick={handleAddCloudFolder}>Add Folder</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 2 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : cloudFolders.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Cloud className="h-10 w-10 mx-auto mb-3 opacity-50" />
              <p className="font-medium">No cloud folders configured</p>
              <p className="text-sm">Add a folder to start automatic polling</p>
            </div>
          ) : (
            <div className="space-y-3">
              {cloudFolders.map((folder) => (
                <div
                  key={folder.id}
                  className="flex items-center justify-between p-4 border rounded-lg hover:bg-accent/50 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <Cloud className="h-5 w-5 text-muted-foreground" />
                    <div>
                      <p className="font-medium">{folder.name}</p>
                      <p className="text-sm text-muted-foreground">
                        {folder.provider.replace('_', ' ')} • {folder.fileCount || 0} files
                        {folder.lastPolled && (
                          <> • Last polled {new Date(folder.lastPolled).toLocaleString()}</>
                        )}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={pollingId === folder.id}
                      onClick={() => handlePollFolder(folder.id)}
                    >
                      {pollingId === folder.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <RefreshCw className="h-4 w-4" />
                      )}
                    </Button>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon">
                          <MoreVertical className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {folder.status === 'active' ? (
                          <DropdownMenuItem>
                            <Pause className="h-4 w-4 mr-2" />
                            Pause Polling
                          </DropdownMenuItem>
                        ) : (
                          <DropdownMenuItem>
                            <Play className="h-4 w-4 mr-2" />
                            Resume Polling
                          </DropdownMenuItem>
                        )}
                        <DropdownMenuItem className="text-destructive">
                          <Trash2 className="h-4 w-4 mr-2" />
                          Remove
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recent Uploads Table */}
      <Card className="shadow-card">
        <CardHeader>
          <CardTitle>Recent Uploads</CardTitle>
          <CardDescription>Latest transcript files added to the system</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>File Name</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Uploaded</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <TableRow key={i}>
                    <TableCell><Skeleton className="h-4 w-40" /></TableCell>
                    <TableCell><Skeleton className="h-4 w-24" /></TableCell>
                    <TableCell><Skeleton className="h-4 w-20" /></TableCell>
                    <TableCell><Skeleton className="h-4 w-28" /></TableCell>
                    <TableCell><Skeleton className="h-4 w-16 ml-auto" /></TableCell>
                  </TableRow>
                ))
              ) : (
                recentUploads.map((upload) => {
                  const status = statusConfig[upload.status];
                  const StatusIcon = status.icon;
                  return (
                    <TableRow key={upload.id}>
                      <TableCell className="font-medium">
                        <div className="flex items-center gap-2">
                          <FileText className="h-4 w-4 text-muted-foreground" />
                          {upload.fileName}
                        </div>
                      </TableCell>
                      <TableCell>
                        {upload.source === 'cloud' ? (
                          <span className="flex items-center gap-1">
                            <Cloud className="h-3 w-3" />
                            {upload.sourceName}
                          </span>
                        ) : (
                          'Manual'
                        )}
                      </TableCell>
                      <TableCell>
                        <span className="flex items-center gap-1.5">
                          <StatusIcon className={cn('h-4 w-4', status.className)} />
                          {status.label}
                        </span>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {new Date(upload.uploadedAt).toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button variant="ghost" size="icon">
                            <Eye className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon">
                            <Download className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon">
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

