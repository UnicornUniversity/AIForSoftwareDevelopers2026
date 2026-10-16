import { Router } from 'express';

import { healthRouter } from './health.js';
import { sunRouter } from './sun.js';
import { webcamsRouter } from './webcams.js';
import { chaseRouter } from './chase.js';

export const apiRouter = Router();

apiRouter.use('/health', healthRouter);
apiRouter.use('/sun', sunRouter);
apiRouter.use('/webcams', webcamsRouter);
apiRouter.use('/sunset-chase', chaseRouter);

apiRouter.get('/', (req, res) => {
  res.json({
    name: 'sunset-chaser',
    version: 1,
    endpoints: [
      'GET /api/v1/health',
      'GET /api/v1/sun/terminator?at=<ISO8601>',
      'GET /api/v1/webcams/near-terminator?limit=<n>',
      'GET /api/v1/webcams/:id',
      'GET /api/v1/sunset-chase?at=<ISO8601>',
    ],
  });
});
