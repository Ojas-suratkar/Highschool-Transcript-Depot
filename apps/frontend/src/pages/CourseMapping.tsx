import { useState } from 'react';
import { Wand2, Check, Link2 } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { StatusBadge } from '@/components/shared/StatusBadge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';

interface Course {
  id: string;
  name: string;
  sourceSchool: string;
  frequency: number;
  suggested: string;
  status: 'pending' | 'mapped';
}

export default function CourseMapping() {
  const [courses, setCourses] = useState<Course[]>([
    { id: '1', name: 'Intro to Programming', sourceSchool: 'Lincoln HS', frequency: 45, suggested: 'CS 101', status: 'pending' },
    { id: '2', name: 'Calculus I', sourceSchool: 'Washington HS', frequency: 38, suggested: 'MATH 140', status: 'pending' },
    { id: '3', name: 'English Composition', sourceSchool: 'Jefferson HS', frequency: 52, suggested: 'ENG 100', status: 'mapped' },
    { id: '4', name: 'Biology Fundamentals', sourceSchool: 'Lincoln HS', frequency: 29, suggested: 'BIO 101', status: 'pending' },
    { id: '5', name: 'World History', sourceSchool: 'Roosevelt HS', frequency: 41, suggested: 'HIST 110', status: 'mapped' },
  ]);

  const [selectedCourse, setSelectedCourse] = useState<Course | null>(null);
  const [referenceCourse, setReferenceCourse] = useState('');
  const [referenceLink, setReferenceLink] = useState('');
  const [confidence, setConfidence] = useState('high');
  const [autoApply, setAutoApply] = useState(false);

  const pendingCount = courses.filter(c => c.status === 'pending').length;
  const mappedCount = courses.filter(c => c.status === 'mapped').length;

  const handleAutoSuggestAll = () => {
    toast.success('Auto-suggestions generated for all courses');
  };

  const handleApproveHighConfidence = () => {
    const updated = courses.map(c =>
      c.status === 'pending' ? { ...c, status: 'mapped' as const } : c
    );
    setCourses(updated);
    toast.success('High confidence mappings approved');
  };

  const handleSelectCourse = (course: Course) => {
    if (course.status === 'pending') {
      setSelectedCourse(course);
      setReferenceCourse(course.suggested);
      setReferenceLink('');
      setConfidence('high');
      setAutoApply(false);
    }
  };

  const handleSaveMapping = () => {
    if (selectedCourse) {
      const updated = courses.map(c =>
        c.id === selectedCourse.id ? { ...c, status: 'mapped' as const } : c
      );
      setCourses(updated);
      setSelectedCourse(null);
      toast.success('Course mapping saved successfully');
    }
  };

  const handleCancel = () => {
    setSelectedCourse(null);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Course Mapping"
        subtitle="Map external courses to institutional equivalents"
      />

      <div className="flex gap-2">
        <Button variant="outline" onClick={handleAutoSuggestAll}>
          <Wand2 className="h-4 w-4 mr-2" />
          Auto-suggest All
        </Button>
        <Button onClick={handleApproveHighConfidence}>
          <Check className="h-4 w-4 mr-2" />
          Approve High Confidence
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Left Panel: Unmapped Courses */}
        <Card className="shadow-sm">
          <CardHeader className="border-b bg-muted/30">
            <CardTitle>Unmapped Courses</CardTitle>
            <CardDescription>{pendingCount} pending, {mappedCount} mapped</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-auto max-h-[600px]">
              <table className="w-full">
                <thead className="bg-muted/50 sticky top-0">
                  <tr className="border-b">
                    <th className="text-left p-3 text-sm font-medium">Course Name</th>
                    <th className="text-left p-3 text-sm font-medium">Source School</th>
                    <th className="text-left p-3 text-sm font-medium">Freq</th>
                    <th className="text-left p-3 text-sm font-medium">Suggested</th>
                    <th className="text-left p-3 text-sm font-medium">Status</th>
                    <th className="text-left p-3 text-sm font-medium">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {courses.map((course) => (
                    <tr
                      key={course.id}
                      className={`border-b hover:bg-muted/30 transition-colors ${
                        selectedCourse?.id === course.id ? 'bg-muted' : ''
                      }`}
                    >
                      <td className="p-3 text-sm font-medium">{course.name}</td>
                      <td className="p-3 text-sm text-muted-foreground">{course.sourceSchool}</td>
                      <td className="p-3 text-sm">{course.frequency}</td>
                      <td className="p-3 text-sm text-primary">{course.suggested}</td>
                      <td className="p-3">
                        <StatusBadge status={course.status} />
                      </td>
                      <td className="p-3">
                        {course.status === 'pending' && (
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleSelectCourse(course)}
                          >
                            <Link2 className="h-4 w-4" />
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        {/* Right Panel: Mapping Editor */}
        <Card className="shadow-sm">
          <CardHeader className="border-b bg-muted/30">
            <CardTitle>Mapping Editor</CardTitle>
          </CardHeader>
          <CardContent className="pt-6">
            {!selectedCourse ? (
              <div className="text-center py-12 text-muted-foreground">
                Select a pending course from the left to create a mapping
              </div>
            ) : (
              <div className="space-y-6">
                {/* Selected Course Display */}
                <div className="bg-muted p-4 rounded-md">
                  <div className="text-lg font-bold">{selectedCourse.name}</div>
                  <div className="text-sm text-muted-foreground">{selectedCourse.sourceSchool}</div>
                </div>

                {/* Reference Course */}
                <div className="space-y-2">
                  <Label htmlFor="referenceCourse">Reference Course</Label>
                  <Select value={referenceCourse} onValueChange={setReferenceCourse}>
                    <SelectTrigger id="referenceCourse">
                      <SelectValue placeholder="Select reference course" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="CS 101">CS 101 - Intro to Computer Science</SelectItem>
                      <SelectItem value="MATH 140">MATH 140 - Calculus I</SelectItem>
                      <SelectItem value="ENG 100">ENG 100 - English Composition</SelectItem>
                      <SelectItem value="BIO 101">BIO 101 - Biology Fundamentals</SelectItem>
                      <SelectItem value="HIST 110">HIST 110 - World History</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {/* Reference Hyperlink */}
                <div className="space-y-2">
                  <Label htmlFor="referenceLink">Reference Hyperlink</Label>
                  <Input
                    id="referenceLink"
                    type="url"
                    placeholder="https://..."
                    value={referenceLink}
                    onChange={(e) => setReferenceLink(e.target.value)}
                  />
                </div>

                {/* Document Upload */}
                <div className="space-y-2">
                  <Label htmlFor="documentUpload">Document Upload</Label>
                  <Input
                    id="documentUpload"
                    type="file"
                  />
                </div>

                {/* Confidence */}
                <div className="space-y-2">
                  <Label htmlFor="confidence">Confidence</Label>
                  <Select value={confidence} onValueChange={setConfidence}>
                    <SelectTrigger id="confidence">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="high">High</SelectItem>
                      <SelectItem value="medium">Medium</SelectItem>
                      <SelectItem value="low">Low</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {/* Auto-apply Toggle */}
                <div className="flex items-center justify-between p-3 bg-muted/30 rounded-md">
                  <Label htmlFor="autoApply" className="cursor-pointer">Auto-apply to similar courses</Label>
                  <Switch
                    id="autoApply"
                    checked={autoApply}
                    onCheckedChange={setAutoApply}
                  />
                </div>

                {/* Action Buttons */}
                <div className="flex gap-3 pt-4">
                  <Button variant="outline" onClick={handleCancel} className="flex-1">
                    Cancel
                  </Button>
                  <Button onClick={handleSaveMapping} className="flex-1">
                    Save Mapping
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
