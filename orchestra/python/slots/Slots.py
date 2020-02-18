
__all__ = ["GPUNode","CPUNode", "Slots"]


from Gaugi import Logger, NotSet
from Gaugi.messenger.macros import *
from Gaugi import retrieve_kw
from Gaugi import StatusCode
from collections import deque
from orchestra import Status
from orchestra.Consumer import Consumer


class Node( object ):
  def __init__(self, name, device=None):
    self.__name = name
    self.__available = True
    self.__device = device
    self.__enable = False

  def name(self):
    return self.__name

  def isAvailable( self ):
    return (self.__available and self.__enable)

  def lock( self ):
    self.__available = False

  def unlock( self ):
    self.__available = True

  # For GPU nodes
  def device(self):
    return self.__device

  def isEnable(self):
    return self.__enable

  def enable(self):
    self.__enable=True

  def disable(self):
    self.__enable=False





class GPUNode( Node ):
  def __init__(self, name, device ):
    Node.__init__( self, name, device )

class CPUNode( Node ):
  def __init__(self, name):
    Node.__init__(self, name)








class Slots( Logger ):

  def __init__(self,name, cluster , queue_name ,  gpu=False) :
    Logger.__init__(self,name=name)

    self.__slots = list()
    self.__available_nodes = list()
    # Just an easier map to node ptr and machine name
    self.__machines = {}
    self.__gpu = gpu
    self.__total = 0

    # necessary infos to retrieve the node from the correct cluster/queue
    self.__queue_name = queue_name
    self.__cluster = cluster


  def setDatabase( self, db ):
    self.__db = db


  def setOrchestrator( self, orc ):
    self.__orchestrator = orc


  def db(self):
    return self.__db


  def orchestrator(self):
    return self.__orchestrator


  def initialize(self):

    if self.db() is NotSet:
      MSG_FATAL( self, "Database object not passed to slot." )

    if self.orchestrator() is NotSet:
      MSG_FATAL( self, "Orchestrator object not passed to slot.")


    # Create all nodes for each machine into the database
    for machine in self.db().getAllMachines( self.__cluster , self.__queue_name):
      if self.__gpu:
        # The node start enable flag as False. You must enable this in the first interation
        self.__machines[machine.getName()] = [ GPUNode(machine.getName(),idx) for idx in range(machine.getMaxGPUJobs()) ]
      else:
        # The node start enable flag as False. You must enable this in the first interation
        self.__machines[machine.getName()] = [ CPUNode(machine.getName()) for _ in range(machine.getMaxCPUJobs()) ]
      self.__available_nodes.extend( self.__machines[machine.getName()] )

      # enable each machine node
      for idx in range( machine.getGPUJobs() if self.__gpu else machine.getCPUJobs() ):
        self.__machines[machine.getName()][idx].enable()

      if self.__gpu:
        for node in self.__machines[machine.getName()]:
          MSG_INFO( self, "Creating a GPU Node(%s) with device %d. This node is enable? %s", node.name(), node.device(), node.isEnable() )
      else:
        MSG_INFO( self, "Creating a CPU Node(%s) with %d/%d", machine.getName(), machine.getCPUJobs(), machine.getMaxCPUJobs() )


    # Count the number of enable slots
    self.__total = 0
    for node in self.__available_nodes:
      if node.isEnable(): self.__total+=1

    MSG_INFO( self, "Creating cluster stack with %d slots", self.size() )
    return StatusCode.SUCCESS





  def execute(self):
    self.update()


    for idx, consumer in enumerate(self.__slots):

      # consumer.status is not DB like, this is internal of kubernetes
      # In DB, the job was activated but here, we put as pending to wait the
      # kubernetes. If everything its ok, the internal status will be change
      # to (running,failed or done).
      if consumer.status() is Status.PENDING:
        # TODO: Change the internal state to RUNNING
        # If, we have an error during the message,
        # we will change to BROKEN status
        if consumer.execute().isFailure():
          # Tell to DB that this job is in broken status
          consumer.job().setStatus( Status.BROKEN )
          consumer.finalize()
          consumer.node().unlock()
          self.__slots.remove(consumer)
        else: # change to running status
          # Tell to DB that this job is running
          consumer.job().setStatus( Status.RUNNING )

      elif consumer.status() is Status.FAILED:
        # Tell to db that this job was failed
        consumer.job().setStatus( Status.FAILED )
        consumer.finalize()
        # Remove this job into the stack
        consumer.node().unlock()

        # increment the failed counter in node table just for monitoring
        self.db().getMachine( self.__cluster, self.__queue_name, consumer.node().name() ).failed( gpu= True if (consumer.node().device() is not None) else False )
        self.__slots.remove(consumer)
      # Kubernetes job is running. Go to the next slot...
      elif consumer.status() is Status.RUNNING:

        # Check if this job in runnning mode was killed by the pilot
        if consumer.job().getStatus() is Status.KILL:
          consumer.kill()

        continue

      elif consumer.status() is Status.DONE:
        consumer.job().setStatus( Status.DONE )
        consumer.finalize()
        consumer.node().unlock()

        # increment the completed counter in node table just for monitoring
        self.db().getMachine( self.__cluster, self.__queue_name, consumer.node().name() ).completed( gpu= True if (consumer.node().device() is not None) else False )
        self.__slots.remove(consumer)

      elif consumer.status() is Status.KILL:
        # Tell to db that this job was killed
        consumer.job().setStatus( Status.KILLED )
        consumer.finalize()
        # Remove this job into the stack
        consumer.node().unlock()
        # increment the killed counter in node table just for monitoring
        #self.db().getMachine( self.__cluster, self.__queue_name, consumer.node().name() ).killed( gpu= True if (consumer.node().device() is not None) else False )
        self.__slots.remove(consumer)

    self.db().commit()



    return StatusCode.SUCCESS


  def finalize(self):
    return StatusCode.SUCCESS


  def size(self):
    return self.__total


  def isAvailable(self):
    return True if len(self.__slots) < self.size() else False


  def allocated( self ):
    return len(self.__slots)


  def empty(self):
    return False if len(self.__slots)>0 else True


  def getAvailableNode(self):
    for node in self.__available_nodes:
      if node.isAvailable():
        return node
    return None



  def update(self):
    before = self.size()
    total = 0
    for machine in self.db().getAllMachines(self.__cluster, self.__queue_name):
      # enable each machine node
      for idx in range( len(self.__machines[machine.getName()]) ):
        if idx < (machine.getGPUJobs() if self.__gpu else machine.getCPUJobs()):
          self.__machines[machine.getName()][idx].enable(); total+=1
        else:
          self.__machines[machine.getName()][idx].disable()

    # Update the total number of enable slots in the list
    self.__total=total

    if self.size()!=before:
      for machine in self.db().getAllMachines(self.__cluster, self.__queue_name):
        if self.__gpu:
          for node in self.__machines[machine.getName()]:
            MSG_INFO( self, "Updating a GPU Node(%s) with device %d. This node is enable? %s", node.name(), node.device(), node.isEnable() )
        else:
          MSG_INFO( self, "Updating a CPU Node(%s) with %d/%d", machine.getName(), machine.getCPUJobs(), machine.getMaxCPUJobs() )





  #
  # Add an job into the stack
  # Job is an db object
  #
  def push_back( self, job ):
    if self.isAvailable():
      node = self.getAvailableNode()
      # Create the job object
      obj = Consumer( job, node )
      # Tell to database that this job will be activated
      obj.setOrchestrator( self.orchestrator() )
      # TODO: the job must set the internal status to ACTIVATED mode
      obj.initialize()
      obj.job().setStatus( Status.ACTIVATED )
      self.__slots.append( obj )
      node.lock()
    else:
      MSG_WARNING( self, "You asked to add one job into the stack but there is no available slots yet." )












