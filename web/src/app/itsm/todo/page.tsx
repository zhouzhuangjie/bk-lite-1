'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

export default function TodoRedirectPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/itsm/tickets?view=todo');
  }, [router]);
  return null;
}
