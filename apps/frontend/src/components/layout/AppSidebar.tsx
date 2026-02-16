import { Link, useLocation } from 'react-router-dom';
import { useState, useEffect } from 'react';
import {
  FileText,
  GraduationCap,
  Cloud,
  Shield,
  CheckCircle2,
  Clock,
  Eye,
  FileCheck,
  Brain,
  UserX,
  TrendingUp,
  Target,
  FileUp,
  Map,
  ChevronDown,
  Mail,
} from 'lucide-react';
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarHeader,
  
  SidebarFooter,
} from '@/components/ui/sidebar';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';

interface MenuItem {
  title: string;
  icon: any;
  path?: string;
  children?: MenuItem[];
}

const menuItems: MenuItem[] = [
  {
    title: 'Admission Information',
    icon: Shield,
    children: [
      {
        title: 'Institutional',
        icon: Shield,
        path: '/admission-criteria',
      },
      {
        title: 'Program',
        icon: GraduationCap,
        path: '/program-criteria',
      },
      {
        title: 'Course Mapping',
        icon: Map,
        path: '/course-mapping',
      },
    ],
  },
  {
    title: 'Admission Metrics',
    icon: Target,
    children: [
      {
        title: 'Enrollment Targets',
        icon: Target,
        path: '/admissions/enrollment-goals',
      },
      {
        title: 'Yield',
        icon: TrendingUp,
        path: '/admissions/yield',
      },
    ],
  },
  {
    title: 'Transcript Uploader',
    icon: FileUp,
    children: [
      {
        title: 'Cloud Folders',
        icon: Cloud,
        path: '/cloud-folders',
      },
    ],
  },
  {
    title: 'New Transcript Type',
    icon: Brain,
    children: [
      {
        title: 'Needs Setup',
        icon: Clock,
        path: '/transcripts/new-types/needs-setup',
      },
      {
        title: 'In Setup',
        icon: CheckCircle2,
        path: '/transcripts/new-types/in-setup',
      },
      {
        title: 'Ready',
        icon: FileCheck,
        path: '/transcripts/new-types/ready',
      },
    ],
  },
  {
    title: 'Transcript Detector',
    icon: FileText,
    children: [
      {
        title: 'Incoming Transcripts',
        icon: FileText,
        path: '/detector/incoming',
      },
      {
        title: 'Existing Transcript Type',
        icon: FileText,
        path: '/detector/existing',
      },
      {
        title: 'New Transcript Type',
        icon: FileText,
        path: '/detector/new-type',
      },
      {
        title: 'Unknown Transcript Type',
        icon: FileText,
        path: '/detector/unknown',
      },
    ],
  },
  {
    title: 'Transcript Extractor',
    icon: FileText,
    children: [
      {
        title: 'Completed',
        icon: CheckCircle2,
        path: '/extractor/completed',
      },
      {
        title: 'Needs Review',
        icon: Eye,
        path: '/extractor/needs-review',
      },
      {
        title: 'Not Processed',
        icon: Clock,
        path: '/extractor/not-processed',
      },
    ],
  },
  {
    title: 'Admission Decision',
    icon: Target,
    children: [
      {
        title: 'Admitted',
        icon: CheckCircle2,
        path: '/decisions/admitted',
      },
      {
        title: 'Denied',
        icon: UserX,
        path: '/decisions/denied',
      },
      {
        title: 'Waitlisted',
        icon: FileText,
        path: '/decisions/waitlisted',
      },
      {
        title: 'Pending Review',
        icon: Clock,
        path: '/decisions/pending',
      },
      {
        title: 'Decision Templates',
        icon: FileText,
        path: '/admissions/templates',
      },
    ],
  },
  
  
];

export function AppSidebar() {
  const location = useLocation();
  const [openSections, setOpenSections] = useState<string[]>(['Admission Information']);

  // Auto-expand section when child route is active
  useEffect(() => {
    menuItems.forEach((item) => {
      if (item.children) {
        const hasActiveChild = item.children.some((child) => child.path === location.pathname);
        if (hasActiveChild && !openSections.includes(item.title)) {
          setOpenSections((prev) => [...prev, item.title]);
        }
      }
    });
  }, [location.pathname]);

  const toggleSection = (title: string) => {
    setOpenSections((prev) =>
      prev.includes(title) ? prev.filter((t) => t !== title) : [...prev, title]
    );
  };

  const renderMenuItem = (item: MenuItem) => {
    const Icon = item.icon;
    const resolvePath = (p?: string) => {
      if (!p) return '/app';
      if (p.startsWith('/')) return `/app${p}`;
      return `/app/${p}`.replace(/\/\//g, '/');
    };

  const itemTo = item.path ? resolvePath(item.path) : '/app';
  const active = itemTo === location.pathname;
  const isOpen = openSections.includes(item.title);

    if (item.children) {
      return (
        <Collapsible
          key={item.title}
          open={isOpen}
          onOpenChange={() => toggleSection(item.title)}
          className="group/collapsible"
        >
          <SidebarGroup>
            <SidebarGroupLabel asChild>
              <CollapsibleTrigger className="group/label w-full flex items-center gap-2">
                <span className="uppercase text-xs text-sidebar-foreground/100 flex-1 text-left">{item.title}</span>
                <ChevronDown className="h-4 w-4 shrink-0 transition-transform group-data-[state=open]/collapsible:rotate-180" />
              </CollapsibleTrigger>
            </SidebarGroupLabel>
            <CollapsibleContent>
              <SidebarGroupContent>
                <SidebarMenu>
                  {item.children.map((child) => {
                    const ChildIcon = child.icon;
                    const to = resolvePath(child.path);
                    const isChildActive = to === location.pathname;
                    return (
                      <SidebarMenuItem key={child.path}>
                        <SidebarMenuButton asChild isActive={isChildActive} className="transition-colors">
                          <Link
                            to={to}
                            className={`flex items-center gap-2 px-3 py-2 rounded-md transition-colors ${
                              isChildActive ? 'bg-blue-600 text-white' : 'text-slate-350 hover:bg-blue-50'
                            }`}
                            >
                              <ChildIcon className={`h-4 w-4 ${isChildActive ? 'text-white' : 'text-slate-350'}`} />
                            <span className="text-sm">{child.title}</span>
                          </Link>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    );
                  })}
                </SidebarMenu>
              </SidebarGroupContent>
            </CollapsibleContent>
          </SidebarGroup>
        </Collapsible>
      );
    }

  const to = resolvePath(item.path);
    return (
      <SidebarMenuItem key={item.path}>
        <SidebarMenuButton asChild isActive={active} className="transition-colors">
          <Link
            to={to}
            className={`flex items-center gap-2 px-3 py-2 rounded-md transition-colors ${
                active ? 'bg-blue-600 text-white' : 'text-slate-350 hover:bg-blue-50'
            }`}
          >
            <Icon className={`h-4 w-4 ${active ? 'text-white' : 'text-slate-350'}`} />
            <span className="text-sm">{item.title}</span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    );
  };

  return (
    <Sidebar className="bg-white border-r border-slate-100">
      {/* Header */}
      <SidebarHeader className="border-b px-4 py-3 bg-white">
        <Link to="/" className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-blue-400 to-cyan-400 shrink-0">
            <GraduationCap className="h-5 w-5 text-white" />
          </div>
          <div className="group-data-[collapsible=icon]:hidden">
            <h2 className="text-base font-bold tracking-tight text-slate-900">Highschool</h2>
            <p className="text-xs text-slate-600">Transcript Depot</p>
          </div>
        </Link>
      </SidebarHeader>

      {/* Content */}
      <SidebarContent>
        {menuItems.map(renderMenuItem)}
      </SidebarContent>

      {/* Footer */}
  <SidebarFooter className="border-t p-4 group-data-[collapsible=icon]:hidden bg-white">
        <div className="space-y-3">
          <div className="text-xs">
            <p className="font-medium">California State University, Long Beach</p>
            <p className="text-sidebar-foreground/70">admin@csulb.edu</p>
          </div>
          <div className="flex items-start gap-2 text-xs text-sidebar-foreground/70">
            <Mail className="h-4 w-4 mt-0.5 shrink-0" />
            <div>
              <p className="font-medium">Need help?</p>
              <p>Contact ira-tech@csulb.edu</p>
            </div>
          </div>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}

