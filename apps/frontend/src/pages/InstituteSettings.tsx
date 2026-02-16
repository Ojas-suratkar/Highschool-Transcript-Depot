import { useState } from 'react';
import { Building2, Save } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/hooks/use-toast';

export default function InstituteSettings() {
  const { toast } = useToast();
  const [settings, setSettings] = useState({
    name: 'University of California, Berkeley',
    code: 'UCB',
    address: '110 Sproul Hall, Berkeley, CA 94720',
    phone: '+1 (510) 642-6000',
    email: 'admissions@berkeley.edu',
    website: 'https://www.berkeley.edu',
    description: 'The University of California, Berkeley is a public research university in Berkeley, California.',
  });

  const handleSave = () => {
    toast({
      title: 'Settings saved',
      description: 'Institute settings have been updated successfully.',
    });
  };

  const handleChange = (field: string, value: string) => {
    setSettings((prev) => ({ ...prev, [field]: value }));
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Institute Settings</h1>
        <p className="text-muted-foreground">Manage your institution's basic information and configuration</p>
      </div>

      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-5 w-5" />
            Institution Information
          </CardTitle>
          <CardDescription>Update your institution's details and contact information</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid gap-6 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="name">Institution Name</Label>
              <Input
                id="name"
                value={settings.name}
                onChange={(e) => handleChange('name', e.target.value)}
                placeholder="Enter institution name"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="code">Institution Code</Label>
              <Input
                id="code"
                value={settings.code}
                onChange={(e) => handleChange('code', e.target.value)}
                placeholder="Enter institution code"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="address">Address</Label>
            <Input
              id="address"
              value={settings.address}
              onChange={(e) => handleChange('address', e.target.value)}
              placeholder="Enter institution address"
            />
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="phone">Phone Number</Label>
              <Input
                id="phone"
                value={settings.phone}
                onChange={(e) => handleChange('phone', e.target.value)}
                placeholder="Enter phone number"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={settings.email}
                onChange={(e) => handleChange('email', e.target.value)}
                placeholder="Enter email address"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="website">Website</Label>
            <Input
              id="website"
              value={settings.website}
              onChange={(e) => handleChange('website', e.target.value)}
              placeholder="Enter website URL"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              value={settings.description}
              onChange={(e) => handleChange('description', e.target.value)}
              placeholder="Enter institution description"
              rows={4}
            />
          </div>

          <div className="flex justify-end">
            <Button onClick={handleSave} className="gap-2">
              <Save className="h-4 w-4" />
              Save Changes
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

