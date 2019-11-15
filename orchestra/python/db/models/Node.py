__all__=['Node']



from sqlalchemy import Column, Integer, String, Date, Float, ForeignKey
from sqlalchemy.orm import relationship
from orchestra.db.models import Base


#
#   Node Table
#
class Node (Base):

  __tablename__ = 'node'

  id        = Column(Integer, primary_key = True)
  name      = Column(String)

  CPUJobs = Column( Integer )
  GPUJobs = Column( Integer )

  maxCPUJobs = Column( Integer )
  maxGPUJobs = Column( Integer )

  CPUCompletedJobs = Column( Integer, default=0 )
  GPUCompletedJobs = Column( Integer, default=0 )

  CPUFailedJobs = Column( Integer, default=0 )
  GPUFailedJobs = Column( Integer, default=0 )



  def getName(self):
    return self.name

  def getMaxCPUJobs(self):
    return self.maxCPUJobs

  def getMaxGPUJobs(self):
    return self.maxGPUJobs

  def getCPUJobs(self):
    return self.CPUJobs

  def getGPUJobs(self):
    return self.GPUJobs


  def completed( self, gpu=False ):
    if gpu:
      self.GPUCompletedJobs+=1
    else:
      self.CPUCompletedJobs+=1


  def failed( self, gpu=False ):
    if gpu:
      self.GPUFailedJobs+=1
    else:
      self.CPUFailedJobs+=1




