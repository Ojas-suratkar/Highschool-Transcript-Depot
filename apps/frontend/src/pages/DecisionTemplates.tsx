import { useState } from 'react';
import { PageHeader } from '@/components/shared/PageHeader';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface Template {
  id: string;
  name: string;
  category: 'admit' | 'decline' | 'i20' | 'verification';
  channel: 'email' | 'letter' | 'sms';
  content: string;
}

export default function DecisionTemplates() {
  const [templates] = useState<Template[]>([
    {
      id: '1',
      name: 'Admission Offer',
      category: 'admit',
      channel: 'email',
      content: 'Dear {{student_name}},\n\nCongratulations! We are pleased to offer you admission to {{program}}...',
    },
    {
      id: '2',
      name: 'Decline Letter',
      category: 'decline',
      channel: 'email',
      content: 'Dear {{student_name}},\n\nThank you for your application to {{program}}...',
    },
    {
      id: '3',
      name: 'I-20 Issuance',
      category: 'i20',
      channel: 'letter',
      content:
        'To: {{student_name}}\n\nPlease find enclosed your Form I-20 (ID: {{i20_id}}) for the program {{program}}.\nIssued on {{decision_date}}.\n\nNext steps:\n- Review the document for accuracy.\n- Sign and return a scanned copy to the admissions office.\n\nIf you have questions, contact international-support@example.edu',
    },
  ]);
  const [selectedTemplate, setSelectedTemplate] = useState<Template>(templates[0]);
  const [showPreview, setShowPreview] = useState(false);

  const categoryColors = {
    admit: 'bg-success/10 text-success border-success/20',
    decline: 'bg-destructive/10 text-destructive border-destructive/20',
    i20: 'bg-purple-500/10 text-purple-600 border-purple-500/20',
    verification: 'bg-warning/10 text-warning border-warning/20',
  };

  const previewContent = selectedTemplate.content
    .replace(/{{student_name}}/g, 'John Doe')
    .replace(/{{program}}/g, 'Computer Science (MS)')
    .replace(/{{decision_date}}/g, new Date().toLocaleDateString());

  return (
    <div className="space-y-6">
      <PageHeader
        title="Decision Templates"
        subtitle="Manage email/letter templates for admissions decisions"
      />

      <div className="grid grid-cols-3 gap-6">
        {/* Left Column: Template List */}
        <div className="space-y-2">
          <h3 className="font-semibold mb-3">Templates</h3>
          {templates.map((template) => (
            <div
              key={template.id}
              className={`p-3 border rounded-lg cursor-pointer transition-colors ${
                selectedTemplate.id === template.id
                  ? 'border-primary bg-primary/5'
                  : 'hover:bg-muted/50'
              }`}
              onClick={() => setSelectedTemplate(template)}
            >
              <div className="font-medium">{template.name}</div>
              <div className="flex gap-2 mt-2">
                <Badge variant="outline" className={categoryColors[template.category]}>
                  {template.category}
                </Badge>
                <Badge variant="outline">{template.channel}</Badge>
              </div>
            </div>
          ))}
        </div>

        {/* Right Column: Template Editor */}
        <div className="col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold">Template Editor</h3>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setShowPreview(!showPreview)}>
                {showPreview ? 'Edit' : 'Preview'}
              </Button>
              <Button variant="outline">Duplicate</Button>
              <Button variant="destructive">Delete</Button>
            </div>
          </div>

          {showPreview ? (
            <div className="border rounded-lg p-6 bg-muted/20 min-h-[400px]">
              <h4 className="font-semibold mb-4">Preview</h4>
              <div className="whitespace-pre-wrap">{previewContent}</div>
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <Label>Template Name</Label>
                <Input value={selectedTemplate.name} className="mt-2" />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>Category</Label>
                  <Select value={selectedTemplate.category}>
                    <SelectTrigger className="mt-2">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="admit">Admit</SelectItem>
                      <SelectItem value="decline">Decline</SelectItem>
                      <SelectItem value="i20">I-20</SelectItem>
                      <SelectItem value="verification">Verification</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <Label>Channel</Label>
                  <Select value={selectedTemplate.channel}>
                    <SelectTrigger className="mt-2">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="email">Email</SelectItem>
                      <SelectItem value="letter">Letter</SelectItem>
                      <SelectItem value="sms">SMS</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div>
                <Label>Content</Label>
                <Textarea
                  value={selectedTemplate.content}
                  className="mt-2 min-h-[300px] font-mono text-sm"
                />
              </div>

              <div>
                <Label>Insert Variable</Label>
                <div className="flex gap-2 mt-2">
                  <Select>
                    <SelectTrigger>
                      <SelectValue placeholder="Select variable" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="student_name">{'{{student_name}}'}</SelectItem>
                      <SelectItem value="program">{'{{program}}'}</SelectItem>
                      <SelectItem value="decision_date">{'{{decision_date}}'}</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button variant="outline">Insert</Button>
                </div>
              </div>

              <Button className="w-full">Save Template</Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

