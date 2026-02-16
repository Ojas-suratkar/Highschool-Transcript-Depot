import { useState, useEffect } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { toast } from 'sonner';

interface Course {
  id: string;
  name: string;
  grade: string; // empty string means placeholder
  credits: number | string; // allow empty string for placeholder
}

interface Transcript {
  id: string;
  studentName: string;
  uploadDate?: string;
  status?: 'processed' | 'failed' | 'queue';
  gpa?: number;
  ucMatch?: boolean;
  reviewReason?: string;
  position?: number;
  school?: string;
  email?: string;
  fileUrl?: string;
}

interface ManualEntryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  transcript?: Transcript;
}

export function ManualEntryDialog({ open, onOpenChange, transcript }: ManualEntryDialogProps) {
  const [studentName, setStudentName] = useState(transcript?.studentName || '');
  const [email, setEmail] = useState(transcript?.email || '');
  const [school, setSchool] = useState(transcript?.school || '');
  const [gpa, setGpa] = useState(transcript?.gpa?.toString() || '');
  const [dateOfBirth, setDateOfBirth] = useState('');
  const [graduationDate, setGraduationDate] = useState('');
  const [courses, setCourses] = useState<Course[]>([{ id: '1', name: '', grade: '', credits: '' }]);

  // Reset form when transcript or open changes
  useEffect(() => {
    setStudentName(transcript?.studentName || '');
    setEmail(transcript?.email || '');
    setSchool(transcript?.school || '');
    setGpa(transcript?.gpa?.toString() || '');
    setDateOfBirth('');
    setGraduationDate('');
    setCourses([{ id: '1', name: '', grade: '', credits: '' }]);
  }, [transcript, open]);

  const handleAddCourse = () => {
    const newId = Math.max(...courses.map((c) => parseInt(c.id)), 0) + 1;
    setCourses([...courses, { id: newId.toString(), name: '', grade: '', credits: '' }]);
  };

  const handleDeleteCourse = (id: string) => {
    if (courses.length > 1) {
      setCourses(courses.filter((c) => c.id !== id));
    }
  };

  const handleUpdateCourse = (id: string, field: keyof Course, value: string | number) => {
    setCourses(courses.map((c) => (c.id === id ? { ...c, [field]: value } : c)));
  };

  const handleSave = () => {
    toast.success('Student information saved successfully');
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-[95vw] w-[95vw] max-h-[90vh] overflow-y-auto p-10"
        style={{ minWidth: '6in', minHeight: '6in' }}
      >
        <DialogHeader>
          <DialogTitle>Manual Student Entry</DialogTitle>
        </DialogHeader>

        <div className="grid grid-cols-1 md:grid-cols-1 gap-6">
          <div className="md:col-span-1">
            <div className="space-y-6">
              {/* Personal Information */}
              <div className="space-y-4">
                <h3 className="font-semibold text-sm">Personal Information</h3>
                <div className="grid grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <Label htmlFor="studentName">Student Name</Label>
                    <Input
                      id="studentName"
                      value={studentName}
                      onChange={(e) => setStudentName(e.target.value)}
                      placeholder="Michael Brown"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="email">Email</Label>
                    <Input
                      id="email"
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="mbrown@email.com"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="school">School</Label>
                    <Input
                      id="school"
                      value={school}
                      onChange={(e) => setSchool(e.target.value)}
                      placeholder="Central High"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="gpa">GPA</Label>
                    <Input
                      id="gpa"
                      type="number"
                      step="0.01"
                      max="4.0"
                      value={gpa}
                      onChange={(e) => setGpa(e.target.value)}
                      placeholder="3.85"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="dateOfBirth">Date of Birth</Label>
                    <Input
                      id="dateOfBirth"
                      type="date"
                      value={dateOfBirth}
                      onChange={(e) => setDateOfBirth(e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="graduationDate">Graduation Date</Label>
                    <Input
                      id="graduationDate"
                      type="date"
                      value={graduationDate}
                      onChange={(e) => setGraduationDate(e.target.value)}
                    />
                  </div>
                </div>
              </div>

              {/* Courses Section */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-sm">Courses</h3>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleAddCourse}
                  >
                    <Plus className="h-4 w-4 mr-2" />
                    Add Course
                  </Button>
                </div>

                <div className="border rounded-lg overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-muted/50">
                        <TableHead>Course Name</TableHead>
                        <TableHead>Grade</TableHead>
                        <TableHead>Credits</TableHead>
                        <TableHead className="w-10">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {courses.map((course) => (
                        <TableRow key={course.id}>
                          <TableCell>
                            <Input
                              value={course.name}
                              onChange={(e) => handleUpdateCourse(course.id, 'name', e.target.value)}
                              placeholder="Course name"
                              className="border-0 px-0"
                            />
                          </TableCell>
                          <TableCell>
                            <Select value={course.grade} onValueChange={(value) => handleUpdateCourse(course.id, 'grade', value)}>
                              <SelectTrigger className="border-0 px-0 w-[80px]">
                                <SelectValue placeholder="Grade" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="A">A</SelectItem>
                                <SelectItem value="B">B</SelectItem>
                                <SelectItem value="C">C</SelectItem>
                                <SelectItem value="D">D</SelectItem>
                                <SelectItem value="F">F</SelectItem>
                              </SelectContent>
                            </Select>
                          </TableCell>
                          <TableCell>
                            <Input
                              type="number"
                              value={course.credits as any}
                              onChange={(e) => handleUpdateCourse(course.id, 'credits', e.target.value ? parseInt(e.target.value) : '')}
                              className="border-0 px-0 w-[60px]"
                              min="0"
                              max="12"
                              placeholder=""
                            />
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleDeleteCourse(course.id)}
                              disabled={courses.length === 1}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>
            </div>
          </div>
        </div>

        <DialogFooter className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button onClick={handleSave}>
            Save Student Information
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
