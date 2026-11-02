import { PlatformAdapter, GenericAdapter } from './genericAdapter';
import { GreenhouseAdapter } from './greenhouseAdapter';
import { LeverAdapter } from './leverAdapter';
import { WorkdayAdapter } from './workdayAdapter';
import { AshbyAdapter } from './ashbyAdapter';

export * from './genericAdapter';
export * from './greenhouseAdapter';
export * from './leverAdapter';
export * from './workdayAdapter';
export * from './ashbyAdapter';

const adapters: PlatformAdapter[] = [
  new GreenhouseAdapter(),
  new LeverAdapter(),
  new WorkdayAdapter(),
  new AshbyAdapter()
];

export function detectAdapter(doc: Document): PlatformAdapter {
  for (const adapter of adapters) {
    if (adapter.detect(doc)) {
      return adapter;
    }
  }
  return new GenericAdapter();
}
